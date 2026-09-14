"""D&D reference libraries (ported from routes/reference.py): the SRD API
sync layer (merged 2024+2014), the nine DM library pages as /api/v1 page
data, homebrew add/edit/delete, the sheet's search/lookup endpoints and the
player-facing read-only browse. JSON paths under /ttrpg/reference keep their
Flask shape; render_template pages became /api/v1/reference/... page data.

Background syncs run in daemon threads under db.session_scope() and emit
`syncjob:<job>` progress; the /sync/status/<job> poller stays for fallback."""
import os
import re
import threading
import time
from datetime import datetime

import requests
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import text

import core.config as config
import core.db as _dbmod
import core.events as events
from core.db import db
from models.ttrpg import (tblArmorLibrary, tblClassesLibrary, tblClassLevelsLibrary, tblConditionsLibrary,
                          tblDnDAPIConfig, tblEquipmentLibrary, tblFeatsLibrary, tblFeaturesLibrary,
                          tblMagicItemsLibrary, tblRacesLibrary, tblRulesLibrary, tblSkillsLibrary,
                          tblSpellsLibrary, tblSubclassesLibrary, tblTraitsLibrary, tblWeaponPropertiesLibrary,
                          tblWeaponsLibrary)
from routers._util import _now, form_or_json, save_upload_downscaled
from security.deps import require_dm, require_user
from core.urls import static_url

router = APIRouter(prefix='/ttrpg/reference')
api = APIRouter(prefix='/api/v1/reference')

WEAPON_IMG_FOLDER = os.path.join(config.UPLOADS_DIR, 'weapons')
ARMOR_IMG_FOLDER = os.path.join(config.UPLOADS_DIR, 'armor')
ALLOWED_IMG_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


def _save_upload(f, subfolder):
    """Save an uploaded image to static/uploads/<subfolder>/; return URL or None."""
    if f is None or not f.filename:
        return None
    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_IMG_EXTS:
        return None
    # Shared Pillow pipeline: downscale to token-art size, opaque->JPEG.
    folder = {'weapons': WEAPON_IMG_FOLDER, 'armor': ARMOR_IMG_FOLDER}.get(
        subfolder, os.path.join(config.UPLOADS_DIR, subfolder))
    filename = save_upload_downscaled(f, folder)
    return static_url(f'uploads/{subfolder}/{filename}')


def _save_weapon_image(f):
    return _save_upload(f, 'weapons')


def _save_armor_image(f):
    return _save_upload(f, 'armor')


_sync_states = {}   # {job_type: {total, done, added, skipped, errors, running, message}}

API_2014 = 'https://www.dnd5eapi.co/api/2014'
API_2024 = 'https://www.dnd5eapi.co/api/2024'
MERGED_API = 'merged'   # sentinel stored in tblDnDAPIConfig — pull 2024 first, fill from 2014

DEFAULT_API_BASE = MERGED_API

API_OPTIONS = {
    MERGED_API: {
        'label':    'Merged — 2024 + 2014 SRD',
        'monsters': '~335',
        'feats':    '~18',
        'weapons':  '~70',
        'note':     'Recommended. Pulls from the 2024 API first and fills everything it '
                    'does not have yet (spells, monsters, rules, subraces…) from 2014.',
    },
    API_2014: {
        'label':    '2014 SRD',
        'monsters': '335',
        'feats':    '1',
        'weapons':  '~67',
        'note':     'Best monster coverage. Limited feats (PHB not open).',
    },
    API_2024: {
        'label':    '2024 (PHB 2024)',
        'monsters': '3',
        'feats':    '17',
        'weapons':  '38',
        'note':     'More feats available, but still incomplete: no spells, monsters, '
                    'rules or per-level class tables yet.',
    },
}


_SPELL_DAMAGE_TYPES = ('acid', 'bludgeoning', 'cold', 'fire', 'force', 'lightning',
                       'necrotic', 'piercing', 'poison', 'psychic', 'radiant',
                       'slashing', 'thunder')


def parse_spell_damage(description):
    """Best-effort extraction of a spell's base damage from its description.

    Returns (damage_dice, damage_type), e.g. ("8d6", "fire"). Grabs the FIRST
    'NdM' found and the nearest damage-type word after it. Approximate: misses
    upcast scaling / save-for-half and may pick the wrong dice for complex
    spells — a DM can correct individual entries later."""
    if not description:
        return '', ''
    m = re.search(r'(\d+)\s*d\s*(\d+)', description)
    if not m:
        return '', ''
    dice = f'{m.group(1)}d{m.group(2)}'
    tail = description[m.end():m.end() + 40].lower()
    dtype = next((t for t in _SPELL_DAMAGE_TYPES if t in tail), '')
    return dice, dtype


def get_api_base():
    s = tblDnDAPIConfig.query.filter_by(key='dnd_api_base').first()
    return s.value if s else DEFAULT_API_BASE


def _api_version(api_base):
    return '2024' if '2024' in api_base else '2014'


def api_label(current=None):
    current = get_api_base() if current is None else current
    return API_OPTIONS.get(current, {}).get('label', 'Custom')


# ── Merged-API fetch layer ─────────────────────────────────────────────────────
# The 2024 API is still being built out (no spells, monsters, rules, subraces,
# per-class level tables…). In merged mode every sync reads BOTH versions:
# 2024 wins where an index exists in both, 2014 fills the gaps. Each entry
# remembers which base it came from so detail fetches and version-specific
# parsing use the right API.

# 2024 renamed some resources; alias per version so 'races' works everywhere.
_RESOURCE_ALIASES = {
    '2024': {'races': 'species', 'subraces': 'subspecies'},
}


def api_sources():
    """API bases to sync from, in priority order (first listing an index wins)."""
    base = get_api_base()
    if base == MERGED_API:
        return [API_2024, API_2014]
    return [base]


def _resource_path(api_base, resource):
    return _RESOURCE_ALIASES.get(_api_version(api_base), {}).get(resource, resource)


def merged_resource_list(resource, list_key='results'):
    """Fetch a resource index from every api_source and merge by 'index'.

    Returns ([(entry, api_base), …], error). A base that lacks the endpoint
    (404 / network error) simply contributes nothing; `error` is set only when
    EVERY source failed, mirroring the old single-base failure behaviour."""
    seen, out, errs = set(), [], []
    ok = False
    for base in api_sources():
        try:
            resp = requests.get(f'{base}/{_resource_path(base, resource)}', timeout=15)
            resp.raise_for_status()
            results = resp.json().get(list_key, [])
            ok = True
        except Exception as e:
            errs.append(f'{_api_version(base)}: {e}')
            continue
        for entry in results:
            idx = entry.get('index')
            if idx and idx not in seen:
                seen.add(idx)
                out.append((entry, base))
    if not ok:
        return [], '; '.join(errs) or 'no API sources responded'
    return out, None


def merged_category_list(category_by_version):
    """Like merged_resource_list but for /equipment-categories/<cat> lists
    (weapons/armor), whose category slug differs per version.
    `category_by_version` maps version -> slug, e.g. {'2014': 'weapon', '2024': 'weapons'}."""
    seen, out, errs = set(), [], []
    ok = False
    for base in api_sources():
        cat = category_by_version.get(_api_version(base))
        if not cat:
            continue
        try:
            resp = requests.get(f'{base}/equipment-categories/{cat}', timeout=15)
            resp.raise_for_status()
            results = resp.json().get('equipment', [])
            ok = True
        except Exception as e:
            errs.append(f'{_api_version(base)}: {e}')
            continue
        for entry in results:
            idx = entry.get('index')
            if idx and idx not in seen:
                seen.add(idx)
                out.append((entry, base))
    if not ok:
        return [], '; '.join(errs) or 'no API sources responded'
    return out, None


def _desc_text(data):
    """Long-form text across API versions: 2014 uses desc (list of paragraphs,
    or a plain string for rule-sections), 2024 uses description (string)."""
    d = data.get('desc')
    if isinstance(d, list):
        return '\n'.join(d)
    if isinstance(d, str):
        return d
    return data.get('description', '') or ''


def _feature_level(data):
    """Feature level across versions: 2014 is an int; 2024 is a ref dict whose
    index ends in the level number (e.g. 'barbarian-4' or 'barbarian-4-nyi')."""
    lvl = data.get('level')
    if isinstance(lvl, int):
        return lvl
    if isinstance(lvl, dict):
        for part in reversed((lvl.get('index') or '').split('-')):
            if part.isdigit():
                return int(part)
    return 0


# ── Sync job runner (shared by every library + the monster sync) ───────────────

class SyncState(dict):
    """The per-job progress dict the sync functions `.update()`; every update
    also fans out over SSE as `syncjob:<job>` (throttled so a 300-entry sync
    doesn't write 300 event rows)."""
    def __init__(self, job):
        super().__init__(total=0, done=0, added=0, skipped=0, errors=0, running=True, message='')
        self.job = job
        self._last_emit = 0.0

    def update(self, *a, **kw):
        super().update(*a, **kw)
        self.emit()

    def emit(self, force=False):
        now = time.monotonic()
        if force or not self.get('running') or now - self._last_emit >= 0.5:
            self._last_emit = now
            events.emit(f'syncjob:{self.job}', dict(self))

    def finish(self, message):
        dict.update(self, running=False, message=message)
        self.emit(force=True)


def start_sync_job(states, key, fn):
    """Start `fn(state=...)` on a daemon thread under a fresh DB session scope.
    Returns the JSON reply for the trigger endpoint ({'job'} or a 409)."""
    if states.get(key, {}).get('running'):
        return JSONResponse({'error': 'Sync already in progress'}, status_code=409)
    state = SyncState(key)
    states[key] = state

    def _run():
        with _dbmod.session_scope():
            try:
                added, skipped, errors = fn(state=state)
            except Exception as e:      # never leave a job stuck on 'running'
                added, skipped, errors = 0, 0, str(e)
            state.finish(f'{added} added, {skipped} skipped, {errors} errors.')
    threading.Thread(target=_run, daemon=True, name=f'sync-{key}').start()
    return {'job': key}


def _status(states, key):
    state = states.get(key, {})
    if not state:
        return {'running': False, 'total': 0, 'done': 0, 'message': ''}
    return dict(state)


# ── Feats sync ─────────────────────────────────────────────────────────────────

def sync_feats_from_api(state=None):
    feat_list, err = merged_resource_list('feats')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(feat_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(feat_list):
        version = _api_version(api_base)
        try:
            index = entry['index']
            if tblFeatsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            try:
                detail = requests.get(f'{api_base}/feats/{index}', timeout=10)
                detail.raise_for_status()
                data = detail.json()

                if version == '2024':
                    description = data.get('description', '')
                    feat_type = data.get('type', '')
                    prerequisites = f'Type: {feat_type.replace("-", " ").title()}' if feat_type else ''
                else:
                    description = '\n'.join(data.get('desc', []))
                    prerequisites = ', '.join(
                        f"{p['ability_score']['name']} {p['minimum_score']}+"
                        for p in data.get('prerequisites', [])
                        if 'ability_score' in p
                    )

                feat = tblFeatsLibrary(
                    api_index=index,
                    name=data['name'],
                    prerequisites=prerequisites,
                    description=description,
                    source='srd',
                    created_at=_now(),
                )
                db.session.add(feat)
                db.session.commit()
                added += 1
            except Exception:
                db.session.rollback()
                errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Weapons sync ───────────────────────────────────────────────────────────────

def sync_weapons_from_api(state=None):
    weapon_list, err = merged_category_list({'2014': 'weapon', '2024': 'weapons'})
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(weapon_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(weapon_list):
        version = _api_version(api_base)
        _outcome = 'skip'
        try:
            index = entry['index']
            if tblWeaponsLibrary.query.filter_by(api_index=index).first():
                _outcome = 'skip'
            else:
                try:
                    detail = requests.get(f'{api_base}/equipment/{index}', timeout=10)

                    if detail.status_code == 404:
                        # Magic weapons live under /magic-items/ instead of /equipment/
                        magic = requests.get(f'{api_base}/magic-items/{index}', timeout=10)
                        if magic.status_code == 404:
                            _outcome = 'skip'
                        else:
                            magic.raise_for_status()
                            mdata = magic.json()
                            desc_lines = mdata.get('desc', [])
                            type_line  = desc_lines[0] if desc_lines else ''
                            full_desc  = '\n'.join(desc_lines[1:]) if len(desc_lines) > 1 else ''
                            raw_img    = mdata.get('image', '')
                            image_url  = ('https://www.dnd5eapi.co' + raw_img) if raw_img else ''
                            w = tblWeaponsLibrary(
                                api_index=index,
                                name=mdata['name'],
                                weapon_category='Magic',
                                weapon_range='',
                                damage_dice='',
                                damage_type='',
                                two_handed_damage_dice='',
                                two_handed_damage_type='',
                                range_normal=0,
                                range_long=0,
                                weight=0,
                                cost='',
                                properties=type_line,
                                mastery='',
                                notes=full_desc,
                                image_url=image_url,
                                source='srd-magic',
                                created_at=_now(),
                            )
                            db.session.add(w)
                            db.session.commit()
                            _outcome = 'add'
                    else:
                        detail.raise_for_status()
                        data = detail.json()

                        if not data.get('damage'):
                            _outcome = 'skip'
                        else:
                            dmg   = data['damage']
                            two_h = data.get('two_handed_damage') or {}
                            cost  = data.get('cost') or {}
                            rng   = data.get('range') or {}
                            throw_rng = data.get('throw_range') or {}

                            if version == '2024':
                                cats = [c['index'] for c in data.get('equipment_categories', [])]
                                weapon_category = ('Martial' if 'martial-weapons' in cats
                                                   else 'Simple' if 'simple-weapons' in cats else '')
                                weapon_range    = ('Ranged' if 'ranged-weapons' in cats
                                                   else 'Melee' if 'melee-weapons' in cats else '')
                                mastery = data.get('mastery', {}).get('name', '') if data.get('mastery') else ''
                            else:
                                weapon_category = data.get('weapon_category', '')
                                weapon_range    = data.get('weapon_range', '')
                                mastery = ''

                            if weapon_range == 'Ranged':
                                range_normal = rng.get('normal', 0)
                                range_long   = rng.get('long', 0)
                            elif throw_rng:
                                range_normal = throw_rng.get('normal', 0)
                                range_long   = throw_rng.get('long', 0)
                            else:
                                range_normal = range_long = 0

                            w = tblWeaponsLibrary(
                                api_index=index,
                                name=data['name'],
                                weapon_category=weapon_category,
                                weapon_range=weapon_range,
                                damage_dice=dmg.get('damage_dice', ''),
                                damage_type=dmg.get('damage_type', {}).get('name', ''),
                                two_handed_damage_dice=two_h.get('damage_dice', ''),
                                two_handed_damage_type=two_h.get('damage_type', {}).get('name', ''),
                                range_normal=range_normal,
                                range_long=range_long,
                                weight=data.get('weight', 0),
                                cost=f"{cost.get('quantity', '')} {cost.get('unit', '')}".strip(),
                                properties=', '.join(p['name'] for p in data.get('properties', [])),
                                mastery=mastery,
                                notes='',
                                image_url='',
                                source='srd',
                                created_at=_now(),
                            )
                            db.session.add(w)
                            db.session.commit()
                            _outcome = 'add'
                except Exception:
                    db.session.rollback()
                    _outcome = 'error'
        except Exception:
            db.session.rollback()
            _outcome = 'error'
        finally:
            if _outcome == 'add':
                added += 1
            elif _outcome == 'skip':
                skipped += 1
            else:
                errors += 1
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── API Settings ───────────────────────────────────────────────────────────────

@api.get('/settings')
def api_settings_page(user=Depends(require_dm)):
    return {'current': get_api_base(), 'api_options': API_OPTIONS, 'default': DEFAULT_API_BASE, 'sync_jobs': SYNC_JOBS}


@api.post('/settings')
def api_settings_save(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    choice = str(form.get('api_choice', '') or '').strip()
    custom = str(form.get('custom_url', '') or '').strip()
    new_url = custom if choice == 'custom' else choice
    if not new_url:
        return JSONResponse({'ok': False, 'error': 'API URL cannot be empty.'}, status_code=400)

    setting = tblDnDAPIConfig.query.filter_by(key='dnd_api_base').first()
    if setting:
        setting.value = new_url
        setting.updated_at = _now()
    else:
        db.session.add(tblDnDAPIConfig(key='dnd_api_base', value=new_url, updated_at=_now()))
    db.session.commit()
    return {'ok': True, 'message': f'API URL updated to: {new_url}', 'current': new_url}


@router.get('/settings/test')
def api_test(url: str = None, user=Depends(require_dm)):
    api_base = (url if url is not None else get_api_base()).strip()
    if api_base == MERGED_API:
        # merged mode has no single URL — test both real bases
        results = []
        for base in (API_2024, API_2014):
            try:
                resp = requests.get(base, timeout=8)
                resp.raise_for_status()
                results.append(f'{_api_version(base)} ok ({len(resp.json())} endpoints)')
            except Exception as e:
                return {'ok': False, 'error': f'{_api_version(base)}: {e}'}
        return {'ok': True, 'endpoints': results}
    try:
        resp = requests.get(api_base, timeout=8)
        resp.raise_for_status()
        keys = list(resp.json().keys())[:8]
        return {'ok': True, 'endpoints': keys}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ── Read-only library browser (all users, incl. players) ────────────────────────

def _join_sub(parts):
    return ' • '.join(p for p in parts if p)


def browse_categories():
    """[(key, label, [{name, sub, desc}])] — the same field set
    relay_broadcaster.push_library sends so both sides match."""
    def _lvl(n):
        return 'Cantrip' if (n or 0) == 0 else f'Level {n}'

    _join = _join_sub
    spells = [{'name': s.name,
               'sub': _join([_lvl(s.level), s.school or '', s.classes_text or '']),
               'desc': s.description or ''}
              for s in tblSpellsLibrary.query.order_by(tblSpellsLibrary.name).all()]
    feats = [{'name': f.name,
              'sub': ('Req: ' + f.prerequisites) if f.prerequisites else '',
              'desc': f.description or ''}
             for f in tblFeatsLibrary.query.order_by(tblFeatsLibrary.name).all()]
    weapons = [{'name': w.name,
                'sub': _join([w.weapon_category or '', w.weapon_range or '',
                              _join([w.damage_dice or '', w.damage_type or '']), w.properties or '']),
                'desc': w.notes or ''}
               for w in tblWeaponsLibrary.query.order_by(tblWeaponsLibrary.name).all()]
    armor = [{'name': a.name,
              'sub': _join([a.armor_category or '',
                            (f'AC {a.armor_class_base}' if a.armor_class_base is not None else ''),
                            ('Stealth disadv.' if a.stealth_disadvantage else '')]),
              'desc': a.notes or ''}
             for a in tblArmorLibrary.query.order_by(tblArmorLibrary.name).all()]
    equipment = [{'name': e.name,
                  'sub': _join([' › '.join([p for p in [e.category, e.subcategory] if p]),
                                e.cost or '', (f'{e.weight} lb' if e.weight else '')]),
                  'desc': e.description or ''}
                 for e in tblEquipmentLibrary.query.order_by(tblEquipmentLibrary.name).all()]
    skills = [{'name': sk.name, 'sub': sk.ability_score or '', 'desc': sk.description or ''}
              for sk in tblSkillsLibrary.query.order_by(tblSkillsLibrary.name).all()]
    races = [{'name': r.name,
              'sub': _join([(f'Speed {r.speed} ft' if r.speed else ''), r.size or '', r.ability_bonuses or '']),
              'desc': r.traits_text or ''}
             for r in tblRacesLibrary.query.order_by(tblRacesLibrary.name).all()]
    classes = [{'name': c.name,
                'sub': _join([(f'd{c.hit_die}' if c.hit_die else ''),
                              c.spellcasting_ability or '', c.saving_throws or '']),
                'desc': c.description or ''}
               for c in tblClassesLibrary.query.order_by(tblClassesLibrary.name).all()]
    conditions = [{'name': c.name, 'sub': '', 'desc': c.description or ''}
                  for c in tblConditionsLibrary.query.order_by(tblConditionsLibrary.name).all()]
    magic_items = [{'name': m.name,
                    'sub': _join([m.category or '', m.rarity or '',
                                  ('Requires attunement' if m.attunement else '')]),
                    'desc': m.description or ''}
                   for m in tblMagicItemsLibrary.query.order_by(tblMagicItemsLibrary.name).all()]
    features = [{'name': f.name,
                 'sub': _join([f.class_name or '', f.subclass_name or '',
                               (f'Level {f.level}' if f.level else '')]),
                 'desc': f.description or ''}
                for f in tblFeaturesLibrary.query.order_by(
                    tblFeaturesLibrary.class_name, tblFeaturesLibrary.level,
                    tblFeaturesLibrary.name).all()]
    subclasses = [{'name': s.name, 'sub': _join([s.class_name or '', s.flavor or '']),
                   'desc': s.description or ''}
                  for s in tblSubclassesLibrary.query.order_by(
                      tblSubclassesLibrary.class_name, tblSubclassesLibrary.name).all()]
    traits = [{'name': t.name, 'sub': t.races_text or '', 'desc': t.description or ''}
              for t in tblTraitsLibrary.query.order_by(tblTraitsLibrary.name).all()]
    weapon_props = [{'name': w.name, 'sub': '', 'desc': w.description or ''}
                    for w in tblWeaponPropertiesLibrary.query.order_by(
                        tblWeaponPropertiesLibrary.name).all()]
    rules = [{'name': r.name, 'sub': r.parent or '', 'desc': r.description or ''}
             for r in tblRulesLibrary.query.order_by(
                 tblRulesLibrary.parent, tblRulesLibrary.name).all()]

    # Sections listed alphabetically by label.
    return [
        ('armor', 'Armor', armor), ('features', 'Class Features', features),
        ('classes', 'Classes', classes), ('conditions', 'Conditions', conditions),
        ('equipment', 'Equipment', equipment), ('feats', 'Feats', feats),
        ('magicitems', 'Magic Items', magic_items), ('races', 'Races', races),
        ('rules', 'Rules', rules), ('skills', 'Skills', skills),
        ('spells', 'Spells', spells), ('subclasses', 'Subclasses', subclasses),
        ('traits', 'Traits', traits), ('weaponprops', 'Weapon Properties', weapon_props),
        ('weapons', 'Weapons', weapons),
    ]


@api.get('/library')
def library_browse(user=Depends(require_user)):
    """Read-only browse of every D&D library for any logged-in user (players
    have no access to the DM library pages). No add/edit/delete/sync here."""
    return {'categories': [{'key': k, 'label': lbl, 'items': items} for k, lbl, items in browse_categories()]}


# ── Clear all libraries (for a clean re-sync) ────────────────────────────────────

@router.post('/libraries/clear')
def libraries_clear(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    """Clear D&D reference libraries so they can be cleanly re-synced.

    scope='srd' (default): delete only API-synced rows, KEEP homebrew — use this
    before Sync All. scope='homebrew': delete only custom (homebrew) rows.
    Characters, sessions, and the monster library are never touched."""
    models = (tblSpellsLibrary, tblFeatsLibrary, tblWeaponsLibrary, tblArmorLibrary,
              tblEquipmentLibrary, tblSkillsLibrary, tblRacesLibrary, tblClassesLibrary,
              tblConditionsLibrary, tblMagicItemsLibrary, tblFeaturesLibrary,
              tblClassLevelsLibrary, tblSubclassesLibrary, tblTraitsLibrary,
              tblWeaponPropertiesLibrary, tblRulesLibrary)
    scope = form.get('scope', 'srd') or 'srd'
    total = 0
    for model in models:
        if scope == 'all':
            q = model.query
        elif scope == 'homebrew':
            q = model.query.filter(model.source == 'homebrew')
        else:  # synced/SRD — everything that isn't homebrew
            q = model.query.filter((model.source != 'homebrew') | (model.source.is_(None)))
        total += q.delete(synchronize_session=False)
    db.session.commit()

    if scope == 'all':
        # Tables are now empty — reset the rowid counters so a fresh Sync All
        # re-creates rows starting at id 1.
        try:
            names = ', '.join(f"'{m.__tablename__}'" for m in models)
            db.session.execute(text(f"DELETE FROM sqlite_sequence WHERE name IN ({names})"))
            db.session.commit()
        except Exception:
            db.session.rollback()
        msg = (f'Cleared ALL {total} library rows and reset IDs to 1. Run "Sync All" now — '
               f'if the re-sync matches, players keep their assigned items.')
    elif scope == 'homebrew':
        msg = f'Cleared {total} homebrew rows from the D&D libraries.'
    else:
        msg = f'Cleared {total} synced (SRD) rows; homebrew kept. Click "Sync All" to repopulate.'
    return {'ok': True, 'message': msg, 'cleared': total}


# ── page-data helpers ───────────────────────────────────────────────────────────

def _row(r):
    """Every column of a library row as plain JSON (the templates read them all)."""
    return {c.name: getattr(r, c.name) for c in r.__table__.columns}


def _page(kind, title, rows, total, filters, **extra):
    current = get_api_base()
    out = {'kind': kind, 'title': title, 'rows': [_row(r) for r in rows], 'total': total,
           'filters': filters, 'current_api': current, 'api_label': api_label(current),
           'api_options': API_OPTIONS}
    out.update(extra)
    return out


def _bad(msg):
    return JSONResponse({'ok': False, 'error': msg}, status_code=400)


def _s(form, key, default=''):
    v = form.get(key, default)
    return default if v is None else str(v).strip()


# ── Feats library ──────────────────────────────────────────────────────────────

@api.get('/feats')
def feats_library(q: str = '', src: str = '', user=Depends(require_dm)):
    total = tblFeatsLibrary.query.count()
    q, src = q.strip(), src.strip()
    feats = tblFeatsLibrary.query
    if q:
        feats = feats.filter(tblFeatsLibrary.name.ilike(f'%{q}%'))
    if src:
        feats = feats.filter(tblFeatsLibrary.source == src)
    feats = feats.order_by(tblFeatsLibrary.name).all()
    return _page('feats', 'Feats Library', feats, total, {'q': q, 'src': src})


@router.post('/feats/sync')
def feats_sync(user=Depends(require_dm)):
    return start_sync_job(_sync_states, 'feats', sync_feats_from_api)


@router.post('/feats/add')
def feat_add(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    name = _s(form, 'name')
    if not name:
        return _bad('Feat name is required.')
    feat = tblFeatsLibrary(
        api_index=None,
        name=name,
        prerequisites=_s(form, 'prerequisites'),
        description=_s(form, 'description'),
        source='homebrew',
        created_at=_now(),
    )
    db.session.add(feat)
    db.session.commit()
    return {'ok': True, 'message': f'Added custom feat "{name}".', 'id': feat.feat_lib_id}


@router.post('/feats/{feat_lib_id}/delete')
def feat_delete(feat_lib_id: int, user=Depends(require_dm)):
    feat = tblFeatsLibrary.query.get_or_404(feat_lib_id)
    if feat.source != 'homebrew':
        return _bad('Only custom feats can be deleted.')
    name = feat.name
    db.session.delete(feat)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}".'}


@router.get('/feats/search')
def feats_search(q: str = '', user=Depends(require_user)):
    q = q.strip()
    feats = tblFeatsLibrary.query.filter(
        tblFeatsLibrary.name.ilike(f'%{q}%')
    ).order_by(tblFeatsLibrary.name).limit(500).all()
    return [{
        'feat_lib_id':   f.feat_lib_id,
        'name':          f.name,
        'prerequisites': f.prerequisites,
        'description':   f.description,
    } for f in feats]


# ── Weapons library ────────────────────────────────────────────────────────────

@router.post('/weapons/add')
def weapon_add(form: dict = Depends(form_or_json), image_file: UploadFile = File(None), user=Depends(require_dm)):
    name = _s(form, 'name')
    if not name:
        return _bad('Weapon name is required.')
    uploaded = _save_weapon_image(image_file)
    image_url = uploaded or _s(form, 'image_url')
    w = tblWeaponsLibrary(
        name                   = name,
        weapon_category        = _s(form, 'weapon_category'),
        weapon_range           = _s(form, 'weapon_range'),
        damage_dice            = _s(form, 'damage_dice'),
        damage_type            = _s(form, 'damage_type'),
        two_handed_damage_dice = _s(form, 'two_handed_damage_dice'),
        two_handed_damage_type = _s(form, 'two_handed_damage_type'),
        range_normal           = int(form.get('range_normal') or 0),
        range_long             = int(form.get('range_long') or 0),
        cost                   = _s(form, 'cost'),
        weight                 = float(form.get('weight') or 0),
        properties             = _s(form, 'properties'),
        mastery                = _s(form, 'mastery'),
        notes                  = _s(form, 'notes'),
        image_url              = image_url,
        source                 = 'homebrew',
        created_at             = datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    )
    db.session.add(w)
    db.session.commit()
    return {'ok': True, 'message': f'Added "{name}" to the weapons library.', 'id': w.weapon_lib_id}


@router.post('/weapons/{weapon_lib_id}/edit')
def weapon_edit(weapon_lib_id: int, form: dict = Depends(form_or_json), image_file: UploadFile = File(None),
                user=Depends(require_dm)):
    w = tblWeaponsLibrary.query.get_or_404(weapon_lib_id)
    w.name                   = _s(form, 'name', w.name) or w.name
    w.weapon_category        = _s(form, 'weapon_category', w.weapon_category)
    w.weapon_range           = _s(form, 'weapon_range', w.weapon_range)
    w.damage_dice            = _s(form, 'damage_dice', w.damage_dice)
    w.damage_type            = _s(form, 'damage_type', w.damage_type)
    w.two_handed_damage_dice = _s(form, 'two_handed_damage_dice', w.two_handed_damage_dice)
    w.two_handed_damage_type = _s(form, 'two_handed_damage_type', w.two_handed_damage_type)
    w.range_normal           = int(form.get('range_normal') or 0)
    w.range_long             = int(form.get('range_long') or 0)
    w.cost                   = _s(form, 'cost', w.cost)
    w.weight                 = float(form.get('weight') or 0)
    w.properties             = _s(form, 'properties', w.properties)
    w.mastery                = _s(form, 'mastery', w.mastery)
    w.notes                  = _s(form, 'notes', w.notes)
    uploaded = _save_weapon_image(image_file)
    if uploaded:
        w.image_url = uploaded
    elif _s(form, 'image_url'):
        w.image_url = _s(form, 'image_url')
    db.session.commit()
    return {'ok': True, 'message': f'Updated "{w.name}".'}


@router.post('/weapons/{weapon_lib_id}/delete')
def weapon_delete(weapon_lib_id: int, user=Depends(require_dm)):
    w = tblWeaponsLibrary.query.get_or_404(weapon_lib_id)
    name = w.name
    db.session.delete(w)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}".'}


@api.get('/weapons')
def weapons_library(q: str = '', cat: str = '', rng: str = '', src: str = '', user=Depends(require_dm)):
    total = tblWeaponsLibrary.query.count()
    q, cat, rng, src = q.strip(), cat.strip(), rng.strip(), src.strip()
    weapons = tblWeaponsLibrary.query
    if q:
        weapons = weapons.filter(tblWeaponsLibrary.name.ilike(f'%{q}%'))
    if cat:
        weapons = weapons.filter(tblWeaponsLibrary.weapon_category == cat)
    if rng:
        weapons = weapons.filter(tblWeaponsLibrary.weapon_range == rng)
    if src:
        weapons = weapons.filter(tblWeaponsLibrary.source == src)
    weapons = weapons.order_by(
        tblWeaponsLibrary.weapon_category,
        tblWeaponsLibrary.weapon_range,
        tblWeaponsLibrary.name
    ).all()
    return _page('weapons', 'Weapons Library', weapons, total, {'q': q, 'cat': cat, 'rng': rng, 'src': src})


@router.post('/weapons/sync')
def weapons_sync(user=Depends(require_dm)):
    return start_sync_job(_sync_states, 'weapons', sync_weapons_from_api)


@router.get('/weapons/search')
def weapons_search(q: str = '', system: str = '', user=Depends(require_user)):
    q = q.strip()
    weapons = _system_filter(tblWeaponsLibrary.query.filter(
        tblWeaponsLibrary.name.ilike(f'%{q}%')
    ), tblWeaponsLibrary, system).order_by(tblWeaponsLibrary.name).limit(500).all()
    return [{
        'weapon_lib_id':          w.weapon_lib_id,
        'name':                   w.name,
        'weapon_category':        w.weapon_category,
        'weapon_range':           w.weapon_range,
        'damage_dice':            w.damage_dice,
        'damage_type':            w.damage_type,
        'two_handed_damage_dice': w.two_handed_damage_dice,
        'two_handed_damage_type': w.two_handed_damage_type,
        'range_normal':           w.range_normal,
        'range_long':             w.range_long,
        'properties':             w.properties,
        'mastery':                w.mastery,
        'cost':                   w.cost,
        'weight':                 w.weight,
        'notes':                  w.notes,
    } for w in weapons]


# ── Armor sync ─────────────────────────────────────────────────────────────────

def sync_armor_from_api(state=None):
    armor_list, err = merged_category_list({'2014': 'armor', '2024': 'armor'})
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(armor_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(armor_list):
        version = _api_version(api_base)
        try:
            index = entry['index']
            if tblArmorLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            # Some armor category entries (e.g. Adamantine/Mithral variants) live
            # under /magic-items/ not /equipment/ — try equipment first, fall back.
            data = None
            for endpoint in ('equipment', 'magic-items'):
                r = requests.get(f'{api_base}/{endpoint}/{index}', timeout=10)
                if r.ok and r.content:
                    try:
                        data = r.json()
                        break
                    except Exception:
                        pass
            if not data:
                skipped += 1
                continue

            ac_obj   = data.get('armor_class', {})
            cost_obj = data.get('cost', {})

            ac_base     = ac_obj.get('base', 0)
            dex_bonus   = 1 if ac_obj.get('dex_bonus') else 0
            max_dex_raw = ac_obj.get('max_bonus')
            if max_dex_raw is None and dex_bonus:
                max_dex_bonus = None
            elif max_dex_raw is not None:
                max_dex_bonus = int(max_dex_raw)
            else:
                max_dex_bonus = 0

            if version == '2024':
                cats = [c['index'] for c in data.get('equipment_categories', [])]
                armor_category = (
                    'Heavy'  if 'heavy-armor'  in cats else
                    'Medium' if 'medium-armor' in cats else
                    'Light'  if 'light-armor'  in cats else
                    'Shield' if 'shield'        in cats else
                    data.get('armor_category', '')
                )
            else:
                armor_category = data.get('armor_category', '')

            a = tblArmorLibrary(
                api_index=index,
                name=data['name'],
                armor_category=armor_category,
                armor_class_base=ac_base,
                dex_bonus=dex_bonus,
                max_dex_bonus=max_dex_bonus,
                str_minimum=data.get('str_minimum', 0) or 0,
                stealth_disadvantage=1 if data.get('stealth_disadvantage') else 0,
                weight=data.get('weight', 0) or 0,
                cost=f"{cost_obj.get('quantity', '')} {cost_obj.get('unit', '')}".strip(),
                properties=', '.join(p.get('name', '') for p in data.get('properties', [])),
                notes=_desc_text(data),
                image_url='',
                source='srd',
                created_at=_now(),
            )
            db.session.add(a)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Armor library routes ────────────────────────────────────────────────────────

def _max_dex(form):
    raw_max = form.get('max_dex_bonus', '')
    return None if raw_max in ('', None) else int(raw_max)


@router.post('/armor/{armor_lib_id}/edit')
def armor_edit(armor_lib_id: int, form: dict = Depends(form_or_json), image_file: UploadFile = File(None),
               user=Depends(require_dm)):
    a = tblArmorLibrary.query.get_or_404(armor_lib_id)
    a.name                = _s(form, 'name', a.name) or a.name
    a.armor_category      = _s(form, 'armor_category', a.armor_category)
    a.armor_class_base    = int(form.get('armor_class_base') or 0)
    a.dex_bonus           = 1 if form.get('dex_bonus') else 0
    a.max_dex_bonus       = _max_dex(form)
    a.str_minimum         = int(form.get('str_minimum') or 0)
    a.stealth_disadvantage = 1 if form.get('stealth_disadvantage') else 0
    a.weight              = float(form.get('weight') or 0)
    a.cost                = _s(form, 'cost', a.cost)
    a.properties          = _s(form, 'properties', a.properties)
    a.notes               = _s(form, 'notes', a.notes)
    uploaded = _save_armor_image(image_file)
    if uploaded:
        a.image_url = uploaded
    elif _s(form, 'image_url'):
        a.image_url = _s(form, 'image_url')
    db.session.commit()
    return {'ok': True, 'message': f'Updated "{a.name}".'}


@router.post('/armor/{armor_lib_id}/delete')
def armor_delete(armor_lib_id: int, user=Depends(require_dm)):
    a = tblArmorLibrary.query.get_or_404(armor_lib_id)
    name = a.name
    db.session.delete(a)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}".'}


@api.get('/armor')
def armor_library(q: str = '', cat: str = '', src: str = '', user=Depends(require_dm)):
    total = tblArmorLibrary.query.count()
    q, cat, src = q.strip(), cat.strip(), src.strip()
    armor = tblArmorLibrary.query
    if q:
        armor = armor.filter(tblArmorLibrary.name.ilike(f'%{q}%'))
    if cat:
        armor = armor.filter(tblArmorLibrary.armor_category == cat)
    if src:
        armor = armor.filter(tblArmorLibrary.source == src)
    armor = armor.order_by(
        tblArmorLibrary.armor_category,
        tblArmorLibrary.name
    ).all()
    return _page('armor', 'Armor & Shields Library', armor, total, {'q': q, 'cat': cat, 'src': src})


@router.post('/armor/sync')
def armor_sync(user=Depends(require_dm)):
    return start_sync_job(_sync_states, 'armor', sync_armor_from_api)


@router.post('/armor/add')
def armor_add(form: dict = Depends(form_or_json), image_file: UploadFile = File(None), user=Depends(require_dm)):
    name = _s(form, 'name')
    if not name:
        return _bad('Armor name is required.')
    a = tblArmorLibrary(
        api_index=None,
        name=name,
        armor_category=_s(form, 'armor_category'),
        armor_class_base=int(form.get('armor_class_base') or 0),
        dex_bonus=1 if form.get('dex_bonus') else 0,
        max_dex_bonus=_max_dex(form),
        str_minimum=int(form.get('str_minimum') or 0),
        stealth_disadvantage=1 if form.get('stealth_disadvantage') else 0,
        weight=float(form.get('weight') or 0),
        cost=_s(form, 'cost'),
        properties=_s(form, 'properties'),
        notes=_s(form, 'notes'),
        image_url=_save_armor_image(image_file) or _s(form, 'image_url'),
        source='homebrew',
        created_at=_now(),
    )
    db.session.add(a)
    db.session.commit()
    return {'ok': True, 'message': f'Added custom armor "{name}".', 'id': a.armor_lib_id}


@router.get('/armor/search')
def armor_search(q: str = '', system: str = '', user=Depends(require_user)):
    q = q.strip()
    armor = _system_filter(tblArmorLibrary.query.filter(
        tblArmorLibrary.name.ilike(f'%{q}%')
    ), tblArmorLibrary, system).order_by(tblArmorLibrary.name).limit(500).all()
    return [{
        'armor_lib_id':      a.armor_lib_id,
        'name':              a.name,
        'armor_category':    a.armor_category,
        'armor_class_base':  a.armor_class_base,
        'dex_bonus':         a.dex_bonus,
        'max_dex_bonus':     a.max_dex_bonus,
        'str_minimum':       a.str_minimum,
        'stealth_disadvantage': a.stealth_disadvantage,
        'cost':              a.cost,
        'weight':            a.weight,
        'properties':        a.properties or '',
        'notes':             a.notes,
        'game_system':       getattr(a, 'game_system', 'dnd5e') or 'dnd5e',
    } for a in armor]


# ── Spells sync ────────────────────────────────────────────────────────────────

def sync_spells_from_api(state=None):
    spell_list, err = merged_resource_list('spells')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(spell_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(spell_list):
        try:
            index = entry['index']
            if tblSpellsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/spells/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            components_list = data.get('components', [])
            material = data.get('material', '')
            if material and 'M' in components_list:
                components_str = ', '.join(components_list) + f' ({material})'
            else:
                components_str = ', '.join(components_list)

            _spell_desc = _desc_text(data)
            _dmg_dice, _dmg_type = parse_spell_damage(_spell_desc)
            spell = tblSpellsLibrary(
                api_index    = index,
                name         = data['name'],
                level        = data.get('level', 0),
                school       = data.get('school', {}).get('name', ''),
                casting_time = data.get('casting_time', ''),
                range_text   = data.get('range', ''),
                components   = components_str,
                duration     = data.get('duration', ''),
                concentration = 1 if data.get('concentration', False) else 0,
                ritual       = 1 if data.get('ritual', False) else 0,
                description  = _spell_desc,
                classes_text = ', '.join(c['name'] for c in data.get('classes', [])),
                damage_dice  = _dmg_dice,
                damage_type  = _dmg_type,
                source       = 'srd',
                created_at   = _now(),
            )
            db.session.add(spell)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Spells library routes ──────────────────────────────────────────────────────

@api.get('/spells')
def spells_library(q: str = '', level: str = '', school: str = '', src: str = '', user=Depends(require_dm)):
    total = tblSpellsLibrary.query.count()
    q, level, school, src = q.strip(), level.strip(), school.strip(), src.strip()
    spells = tblSpellsLibrary.query
    if q:
        spells = spells.filter(tblSpellsLibrary.name.ilike(f'%{q}%'))
    if level != '':
        try:
            spells = spells.filter(tblSpellsLibrary.level == int(level))
        except ValueError:
            pass
    if school:
        spells = spells.filter(tblSpellsLibrary.school == school)
    if src:
        spells = spells.filter(tblSpellsLibrary.source == src)
    spells = spells.order_by(tblSpellsLibrary.level, tblSpellsLibrary.name).all()
    return _page('spells', 'Spells Library', spells, total, {'q': q, 'level': level, 'school': school, 'src': src})


@router.post('/spells/sync')
def spells_sync(user=Depends(require_dm)):
    return start_sync_job(_sync_states, 'spells', sync_spells_from_api)


@router.post('/spells/add')
def spell_add(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    name = _s(form, 'name')
    if not name:
        return _bad('Spell name is required.')
    _desc = _s(form, 'description')
    _dmg_dice, _dmg_type = parse_spell_damage(_desc)
    spell = tblSpellsLibrary(
        api_index    = None,
        name         = name,
        level        = int(form.get('level', 0) or 0),
        school       = _s(form, 'school'),
        casting_time = _s(form, 'casting_time'),
        range_text   = _s(form, 'range_text'),
        components   = _s(form, 'components'),
        duration     = _s(form, 'duration'),
        concentration = 1 if form.get('concentration') else 0,
        ritual       = 1 if form.get('ritual') else 0,
        description  = _desc,
        classes_text = _s(form, 'classes_text'),
        damage_dice  = _dmg_dice,
        damage_type  = _dmg_type,
        source       = 'homebrew',
        created_at   = _now(),
    )
    db.session.add(spell)
    db.session.commit()
    return {'ok': True, 'message': f'Added custom spell "{name}".', 'id': spell.spell_lib_id}


@router.post('/spells/{spell_lib_id}/delete')
def spell_delete(spell_lib_id: int, user=Depends(require_dm)):
    spell = tblSpellsLibrary.query.get_or_404(spell_lib_id)
    if spell.source != 'homebrew':
        return _bad('Only custom spells can be deleted.')
    name = spell.name
    db.session.delete(spell)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}".'}


@router.get('/spells/search')
def spells_search(q: str = '', level: str = '', school: str = '', src: str = '', limit: int = 20,
                  user=Depends(require_user)):
    q, level, school, src = q.strip(), level.strip(), school.strip(), src.strip()
    spells = tblSpellsLibrary.query
    if q:
        spells = spells.filter(tblSpellsLibrary.name.ilike(f'%{q}%'))
    if level != '':
        try:
            spells = spells.filter(tblSpellsLibrary.level == int(level))
        except ValueError:
            pass
    if school:
        spells = spells.filter(tblSpellsLibrary.school == school)
    if src:
        spells = spells.filter(tblSpellsLibrary.source == src)
    spells = spells.order_by(tblSpellsLibrary.level, tblSpellsLibrary.name).limit(limit).all()
    return [{
        'spell_lib_id': s.spell_lib_id,
        'name':         s.name,
        'level':        s.level,
        'school':       s.school,
        'casting_time': s.casting_time,
        'range_text':   s.range_text,
        'components':   s.components,
        'duration':     s.duration,
        'concentration': s.concentration,
        'ritual':       s.ritual,
        'description':  s.description,
        'classes_text': s.classes_text,
        'source':       s.source,
    } for s in spells]


# ── Skills sync ────────────────────────────────────────────────────────────────

def sync_skills_from_api(state=None):
    skill_list, err = merged_resource_list('skills')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(skill_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(skill_list):
        try:
            index = entry['index']
            if tblSkillsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/skills/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            ability_obj = data.get('ability_score', {})
            ability_score = ability_obj.get('name', '') or ability_obj.get('index', '').upper()

            skill = tblSkillsLibrary(
                api_index     = index,
                name          = data['name'],
                ability_score = ability_score,
                description   = _desc_text(data),
                source        = 'srd',
                created_at    = _now(),
            )
            db.session.add(skill)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Skills library routes ──────────────────────────────────────────────────────

def _game_system_arg(src):
    """'dnd5e' | 'dcc' from a form/query dict (anything else → dnd5e)."""
    import ttrpg.dice_systems as dice_systems
    v = (src.get('game_system') or '').strip()
    return v if v in dice_systems.SYSTEMS else dice_systems.DEFAULT_SYSTEM


def _skill_category(s):
    """DCC skill category: from the built-in data, else the 'Category.' prefix a
    DM typed into a custom row's description."""
    import ttrpg.dcc_library as dcc_library
    if s.game_system != 'dcc':
        return ''
    meta = dcc_library.SKILL_INDEX.get(s.name)
    if meta:
        return meta[0]
    head = (s.description or '').split('.', 1)[0].strip()
    return head if head in ('Attack', 'Spell', 'Utility', 'Passive') else ''


def _system_filter(query, model, system=''):
    """Search endpoints: `?system=dcc` narrows to that system; `?system=all`
    or no arg returns everything (old callers keep working)."""
    system = (system or '').strip()
    if system and system != 'all':
        return query.filter(model.game_system == system)
    return query


@router.post('/library/dcc/restore')
def dcc_library_restore(user=Depends(require_dm)):
    """Re-insert any built-in Dungeon Crawler Carl entries that were deleted.
    Edited rows are untouched (matched by api_index)."""
    import ttrpg.dcc_library as dcc_library
    import models.ttrpg as _m
    n = dcc_library.seed(db, _m, _now())
    return {'ok': True, 'restored': n,
            'message': (f'Restored {n} built-in Dungeon Crawler Carl entries.' if n
                        else 'All built-in Dungeon Crawler Carl entries are already present.')}


@api.get('/skills')
def skills_library(q: str = '', src: str = '', system: str = '', user=Depends(require_dm)):
    total = tblSkillsLibrary.query.count()
    q, src, system = q.strip(), src.strip(), system.strip()
    skills = tblSkillsLibrary.query
    if q:
        skills = skills.filter(tblSkillsLibrary.name.ilike(f'%{q}%'))
    if src:
        skills = skills.filter(tblSkillsLibrary.source == src)
    if system:
        skills = skills.filter(tblSkillsLibrary.game_system == system)
    skills = skills.order_by(tblSkillsLibrary.ability_score, tblSkillsLibrary.name).all()
    return _page('skills', 'Skills Library', skills, total, {'q': q, 'src': src, 'system': system}, system=system)


@router.post('/skills/sync')
def skills_sync(user=Depends(require_dm)):
    return start_sync_job(_sync_states, 'skills', sync_skills_from_api)


@router.post('/skills/add')
def skill_add_to_lib(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    name = _s(form, 'name')
    if not name:
        return _bad('Skill name is required.')
    skill = tblSkillsLibrary(
        api_index     = None,
        name          = name,
        ability_score = _s(form, 'ability_score'),
        description   = _s(form, 'description'),
        source        = 'homebrew',
        created_at    = _now(),
        game_system = _game_system_arg(form),
    )
    db.session.add(skill)
    db.session.commit()
    return {'ok': True, 'message': f'Added custom skill "{name}".', 'id': skill.skill_lib_id}


@router.post('/skills/{skill_lib_id}/delete')
def skill_lib_delete(skill_lib_id: int, user=Depends(require_dm)):
    skill = tblSkillsLibrary.query.get_or_404(skill_lib_id)
    if skill.source not in ('homebrew', 'dcc'):
        return _bad('Only custom skills can be deleted.')
    name = skill.name
    db.session.delete(skill)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}".'}


@router.get('/skills/search')
def skills_search(q: str = '', system: str = '', user=Depends(require_user)):
    q = q.strip()
    skills = tblSkillsLibrary.query.filter(tblSkillsLibrary.name.ilike(f'%{q}%'))
    skills = _system_filter(skills, tblSkillsLibrary, system)
    skills = skills.order_by(tblSkillsLibrary.ability_score, tblSkillsLibrary.name).limit(40).all()
    return [{
        'skill_lib_id': s.skill_lib_id,
        'name':         s.name,
        'ability_score': s.ability_score,
        'description':  s.description,
        'source':       s.source,
        'game_system':  s.game_system or 'dnd5e',
        # DCC: category (Attack/Spell/Utility/Passive) so the sheet can preset it
        'category':     _skill_category(s),
    } for s in skills]


# ── Races sync ─────────────────────────────────────────────────────────────────

def sync_races_from_api(state=None):
    # merged mode: 2024 renamed races -> species (aliased); species entries lack
    # ability bonuses/languages, which stay blank — 2014 fills classic races.
    race_list, err = merged_resource_list('races')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(race_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(race_list):
        try:
            index = entry['index']
            if tblRacesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/{_resource_path(api_base, "races")}/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            ability_bonuses = ', '.join(
                f"+{ab['bonus']} {ab['ability_score']['name']}"
                for ab in data.get('ability_bonuses', [])
            )

            race = tblRacesLibrary(
                api_index      = index,
                name           = data['name'],
                speed          = data.get('speed', 30),
                size           = data.get('size', ''),
                ability_bonuses = ability_bonuses,
                traits_text    = '\n'.join(t['name'] for t in data.get('traits', [])),
                languages      = ', '.join(lang['name'] for lang in data.get('languages', [])),
                description    = data.get('alignment', ''),
                source         = 'srd',
                created_at     = _now(),
            )
            db.session.add(race)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Races library routes ───────────────────────────────────────────────────────

@api.get('/races')
def races_library(q: str = '', src: str = '', system: str = '', user=Depends(require_dm)):
    total = tblRacesLibrary.query.count()
    q, src, system = q.strip(), src.strip(), system.strip()
    races = tblRacesLibrary.query
    if q:
        races = races.filter(tblRacesLibrary.name.ilike(f'%{q}%'))
    if src:
        races = races.filter(tblRacesLibrary.source == src)
    if system:
        races = races.filter(tblRacesLibrary.game_system == system)
    races = races.order_by(tblRacesLibrary.name).all()
    return _page('races', 'Races Library', races, total, {'q': q, 'src': src, 'system': system}, system=system)


@router.post('/races/sync')
def races_sync(user=Depends(require_dm)):
    return start_sync_job(_sync_states, 'races', sync_races_from_api)


@router.post('/races/add')
def race_add(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    name = _s(form, 'name')
    if not name:
        return _bad('Race name is required.')
    race = tblRacesLibrary(
        api_index       = None,
        name            = name,
        speed           = int(form.get('speed', 30) or 30),
        size            = _s(form, 'size'),
        ability_bonuses = _s(form, 'ability_bonuses'),
        traits_text     = _s(form, 'traits_text'),
        languages       = _s(form, 'languages'),
        description     = _s(form, 'description'),
        source          = 'homebrew',
        created_at      = _now(),
        game_system = _game_system_arg(form),
    )
    db.session.add(race)
    db.session.commit()
    return {'ok': True, 'message': f'Added custom race "{name}".', 'id': race.race_lib_id}


@router.post('/races/{race_lib_id}/delete')
def race_delete(race_lib_id: int, user=Depends(require_dm)):
    race = tblRacesLibrary.query.get_or_404(race_lib_id)
    if race.source not in ('homebrew', 'dcc'):
        return _bad('Only custom races can be deleted.')
    name = race.name
    db.session.delete(race)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}".'}


# ── Equipment Library ───────────────────────────────────────────────────────────

SKIP_EQUIPMENT_CATEGORIES = {'armor', 'weapon', 'weapons', 'armor and shields'}


def sync_equipment_from_api(state=None):
    eq_list, err = merged_resource_list('equipment')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(eq_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(eq_list):
        try:
            index = entry['index']
            if tblEquipmentLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            r = requests.get(f'{api_base}/equipment/{index}', timeout=10)
            if not r.ok or not r.content:
                skipped += 1
                continue
            data = r.json()

            cat = (data.get('equipment_category') or {}).get('name', '')
            if cat.lower() in SKIP_EQUIPMENT_CATEGORIES:
                skipped += 1
                continue

            subcat = (data.get('gear_category') or
                      data.get('tool_category') or
                      data.get('vehicle_category') or {})
            if isinstance(subcat, dict):
                subcat = subcat.get('name', '')
            else:
                subcat = ''

            cost_obj = data.get('cost', {})
            cost_str = f"{cost_obj.get('quantity', 0)} {cost_obj.get('unit', 'gp')}" if cost_obj else ''

            item = tblEquipmentLibrary(
                api_index   = index,
                name        = data.get('name', index),
                category    = cat,
                subcategory = subcat,
                weight      = float(data.get('weight', 0) or 0),
                cost        = cost_str,
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            )
            db.session.add(item)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})

    return added, skipped, errors


@api.get('/equipment')
def equipment_library(q: str = '', cat: str = '', src: str = '', user=Depends(require_dm)):
    total = tblEquipmentLibrary.query.count()
    q, cat, src = q.strip(), cat.strip(), src.strip()
    query = tblEquipmentLibrary.query
    if q:
        query = query.filter(tblEquipmentLibrary.name.ilike(f'%{q}%'))
    if cat:
        query = query.filter(tblEquipmentLibrary.category == cat)
    if src:
        query = query.filter(tblEquipmentLibrary.source == src)
    items = query.order_by(tblEquipmentLibrary.category, tblEquipmentLibrary.name).all()

    categories = sorted({i.category for i in tblEquipmentLibrary.query.all() if i.category})
    return _page('equipment', 'Equipment Library', items, total, {'q': q, 'cat': cat, 'src': src},
                 categories=categories)


@router.post('/equipment/sync')
def equipment_sync(user=Depends(require_dm)):
    return start_sync_job(_sync_states, 'equipment', sync_equipment_from_api)


@router.get('/sync/status/{job_type}')
def sync_status(job_type: str, user=Depends(require_user)):
    return _status(_sync_states, job_type)


@router.post('/equipment/add')
def equipment_add(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    name = _s(form, 'name')
    if not name:
        return _bad('Item name is required.')
    item = tblEquipmentLibrary(
        api_index   = None,
        name        = name,
        category    = _s(form, 'category'),
        subcategory = _s(form, 'subcategory'),
        weight      = float(form.get('weight', 0) or 0),
        cost        = _s(form, 'cost'),
        description = _s(form, 'description'),
        source      = 'homebrew',
        created_at  = _now(),
    )
    db.session.add(item)
    db.session.commit()
    return {'ok': True, 'message': f'Added "{name}".', 'id': item.equipment_lib_id}


@router.post('/equipment/{equipment_lib_id}/delete')
def equipment_delete(equipment_lib_id: int, user=Depends(require_dm)):
    item = tblEquipmentLibrary.query.get_or_404(equipment_lib_id)
    if item.source != 'homebrew':
        return _bad('Only custom items can be deleted.')
    name = item.name
    db.session.delete(item)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}".'}


@router.get('/equipment/search')
def equipment_search(q: str = '', system: str = '', user=Depends(require_user)):
    q = q.strip()
    items = _system_filter(tblEquipmentLibrary.query.filter(
        tblEquipmentLibrary.name.ilike(f'%{q}%')
    ), tblEquipmentLibrary, system).order_by(tblEquipmentLibrary.name).limit(500).all()
    return [{
        'equipment_lib_id': i.equipment_lib_id,
        'name':             i.name,
        'category':         i.category,
        'subcategory':      i.subcategory,
        'weight':           i.weight,
        'cost':             i.cost,
        'description':      i.description,
    } for i in items]


# ── Classes sync ────────────────────────────────────────────────────────────────

def sync_classes_from_api(state=None):
    class_list, err = merged_resource_list('classes')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(class_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(class_list):
        try:
            index = entry['index']
            if tblClassesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/classes/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            saving_throws = ', '.join(st['name'] for st in data.get('saving_throws', []))

            # All proficiencies except saving-throw entries
            profs = [p['name'] for p in data.get('proficiencies', [])
                     if not p['name'].startswith('Saving Throw')]
            proficiencies = ', '.join(profs)

            # Skill choices description
            skill_choices = ''
            for choice in data.get('proficiency_choices', []):
                desc = choice.get('desc', '')
                if desc:
                    skill_choices = desc
                    break

            subclasses = ', '.join(sc['name'] for sc in data.get('subclasses', []))

            spell_obj = data.get('spellcasting', {})
            spellcasting_ability = (spell_obj.get('spellcasting_ability', {}) or {}).get('name', '')

            cls = tblClassesLibrary(
                api_index            = index,
                name                 = data['name'],
                hit_die              = data.get('hit_die', 8),
                saving_throws        = saving_throws,
                proficiencies        = proficiencies,
                skill_choices        = skill_choices,
                subclasses           = subclasses,
                spellcasting_ability = spellcasting_ability,
                description          = '',
                source               = 'srd',
                created_at           = _now(),
            )
            db.session.add(cls)
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Classes library routes ─────────────────────────────────────────────────────

@api.get('/classes')
def classes_library(q: str = '', src: str = '', system: str = '', user=Depends(require_dm)):
    total = tblClassesLibrary.query.count()
    q, src, system = q.strip(), src.strip(), system.strip()
    classes = tblClassesLibrary.query
    if q:
        classes = classes.filter(tblClassesLibrary.name.ilike(f'%{q}%'))
    if src:
        classes = classes.filter(tblClassesLibrary.source == src)
    if system:
        classes = classes.filter(tblClassesLibrary.game_system == system)
    classes = classes.order_by(tblClassesLibrary.name).all()
    return _page('classes', 'Classes Library', classes, total, {'q': q, 'src': src, 'system': system}, system=system)


@router.post('/classes/sync')
def classes_sync(user=Depends(require_dm)):
    return start_sync_job(_sync_states, 'classes', sync_classes_from_api)


@router.post('/classes/add')
def class_add(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    name = _s(form, 'name')
    if not name:
        return _bad('Class name is required.')
    cls = tblClassesLibrary(
        api_index            = None,
        name                 = name,
        hit_die              = int(form.get('hit_die', 8) or 8),
        saving_throws        = _s(form, 'saving_throws'),
        proficiencies        = _s(form, 'proficiencies'),
        skill_choices        = _s(form, 'skill_choices'),
        subclasses           = _s(form, 'subclasses'),
        spellcasting_ability = _s(form, 'spellcasting_ability'),
        description          = _s(form, 'description'),
        source               = 'homebrew',
        created_at           = _now(),
        game_system = _game_system_arg(form),
    )
    db.session.add(cls)
    db.session.commit()
    return {'ok': True, 'message': f'Added custom class "{name}".', 'id': cls.class_lib_id}


@router.post('/classes/{class_lib_id}/delete')
def class_delete(class_lib_id: int, user=Depends(require_dm)):
    cls = tblClassesLibrary.query.get_or_404(class_lib_id)
    if cls.source not in ('homebrew', 'dcc'):
        return _bad('Only custom classes can be deleted.')
    name = cls.name
    db.session.delete(cls)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}".'}


@router.get('/races/search')
def races_search(q: str = '', system: str = '', user=Depends(require_user)):
    q = q.strip()
    races = _system_filter(tblRacesLibrary.query.filter(
        tblRacesLibrary.name.ilike(f'%{q}%')), tblRacesLibrary, system
    ).order_by(tblRacesLibrary.name).limit(500).all()
    return [{
        'race_lib_id':    r.race_lib_id,
        'name':           r.name,
        'speed':          r.speed,
        'size':           r.size,
        'ability_bonuses': r.ability_bonuses,
        'traits_text':    r.traits_text,
        'languages':      r.languages,
        'description':    r.description,
        'game_system':    r.game_system or 'dnd5e',
    } for r in races]


# ── Conditions sync ─────────────────────────────────────────────────────────────

def sync_conditions_from_api(state=None):
    cond_list, err = merged_resource_list('conditions')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(cond_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(cond_list):
        try:
            index = entry['index']
            if tblConditionsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/conditions/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            db.session.add(tblConditionsLibrary(
                api_index   = index,
                name        = data['name'],
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Magic items sync ────────────────────────────────────────────────────────────

def sync_magic_items_from_api(state=None):
    item_list, err = merged_resource_list('magic-items')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(item_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(item_list):
        try:
            index = entry['index']
            if tblMagicItemsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/magic-items/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            description = _desc_text(data)
            # attunement: explicit bool on 2024; 2014 states it in the type line
            # of desc[0], e.g. "Wondrous item, rare (requires attunement)"
            attune = data.get('attunement')
            if attune is None:
                attune = 'requires attunement' in description[:200].lower()
            raw_img = data.get('image', '')
            db.session.add(tblMagicItemsLibrary(
                api_index   = index,
                name        = data['name'],
                category    = (data.get('equipment_category') or {}).get('name', ''),
                rarity      = (data.get('rarity') or {}).get('name', ''),
                attunement  = 1 if attune else 0,
                description = description,
                image_url   = ('https://www.dnd5eapi.co' + raw_img) if raw_img else '',
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Class features sync ─────────────────────────────────────────────────────────

def sync_features_from_api(state=None):
    feature_list, err = merged_resource_list('features')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(feature_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(feature_list):
        try:
            index = entry['index']
            if tblFeaturesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/features/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            prereqs = ', '.join(
                p.get('name', p.get('type', '')) if isinstance(p, dict) else str(p)
                for p in data.get('prerequisites', [])
            )
            cls_name = (data.get('class') or {}).get('name', '')
            sub_name = (data.get('subclass') or {}).get('name', '')
            level    = _feature_level(data)
            # The two API editions index the same feature differently ('rage' vs
            # 'barbarian-rage'), so index dedup alone would store both editions.
            # Skip when the class/subclass/level/name combination already exists —
            # in merged mode 2024 syncs first, so its text wins.
            from sqlalchemy import func as _f
            if (tblFeaturesLibrary.query
                    .filter(_f.lower(tblFeaturesLibrary.name) == data['name'].lower(),
                            _f.lower(tblFeaturesLibrary.class_name) == cls_name.lower(),
                            _f.lower(tblFeaturesLibrary.subclass_name) == sub_name.lower(),
                            tblFeaturesLibrary.level == level)
                    .first()):
                skipped += 1
                continue
            db.session.add(tblFeaturesLibrary(
                api_index     = index,
                name          = data['name'],
                class_name    = cls_name,
                subclass_name = sub_name,
                level         = level,
                prerequisites = prereqs,
                description   = _desc_text(data),
                source        = 'srd',
                created_at    = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Class level tables sync (proficiency bonus, spell slots, class counters) ────

def sync_class_levels_from_api(state=None):
    """Per-level progression for every class: /classes/{index}/levels.

    Only the 2014 API serves level tables today; in merged mode each class
    tries its own base first, then the remaining sources — so 2024-sourced
    classes still get their 2014 progression."""
    import json as _json
    class_list, err = merged_resource_list('classes')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(class_list) * 20   # ~20 levels per class

    added = skipped = errors = 0
    done = 0
    for entry, entry_base in class_list:
        index = entry['index']
        levels = []
        bases = [entry_base] + [b for b in api_sources() if b != entry_base]
        for base in bases:
            try:
                resp = requests.get(f'{base}/classes/{index}/levels', timeout=15)
                if not resp.ok or not resp.content:
                    continue
                data = resp.json()
                if isinstance(data, list) and data:
                    levels = data
                    break
            except Exception:
                continue

        for lvl in levels:
            done += 1
            try:
                # subclass-specific level rows ride along in some tables — skip them
                if lvl.get('subclass'):
                    skipped += 1
                    continue
                lvl_no = lvl.get('level', 0)
                api_idx = lvl.get('index') or f'{index}-{lvl_no}'
                if tblClassLevelsLibrary.query.filter_by(api_index=api_idx).first():
                    skipped += 1
                    continue
                spellcasting = lvl.get('spellcasting') or {}
                slots = {str(n): spellcasting.get(f'spell_slots_level_{n}', 0) or 0
                         for n in range(1, 10)}
                db.session.add(tblClassLevelsLibrary(
                    api_index      = api_idx,
                    class_name     = (lvl.get('class') or {}).get('name', index.title()),
                    level          = lvl_no,
                    prof_bonus     = lvl.get('prof_bonus', 2) or 2,
                    features_text  = '\n'.join(f['name'] for f in lvl.get('features', [])),
                    cantrips_known = spellcasting.get('cantrips_known', 0) or 0,
                    spells_known   = spellcasting.get('spells_known', 0) or 0,
                    spell_slots_json    = _json.dumps(slots),
                    class_specific_json = _json.dumps(lvl.get('class_specific') or {}),
                    source         = 'srd',
                    created_at     = _now(),
                ))
                db.session.commit()
                added += 1
            except Exception:
                db.session.rollback()
                errors += 1
            finally:
                if state is not None:
                    state.update({'done': done, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Subclasses sync ─────────────────────────────────────────────────────────────

def sync_subclasses_from_api(state=None):
    sub_list, err = merged_resource_list('subclasses')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(sub_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(sub_list):
        try:
            index = entry['index']
            if tblSubclassesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/subclasses/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            description = _desc_text(data)
            # 2024 embeds the subclass features right in the detail — keep them
            # with the description so the archetype reads as one entry.
            embedded = data.get('features')
            if isinstance(embedded, list) and embedded:
                lines = [f"L{f.get('level', '?')} {f.get('name', '')}: {f.get('description', '')}"
                         for f in embedded if isinstance(f, dict)]
                description = (description + '\n\n' + '\n\n'.join(lines)).strip()

            db.session.add(tblSubclassesLibrary(
                api_index   = index,
                name        = data['name'],
                class_name  = (data.get('class') or {}).get('name', ''),
                flavor      = data.get('subclass_flavor') or data.get('summary', ''),
                description = description,
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Racial traits sync ──────────────────────────────────────────────────────────

def sync_traits_from_api(state=None):
    trait_list, err = merged_resource_list('traits')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(trait_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(trait_list):
        try:
            index = entry['index']
            if tblTraitsLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/traits/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()

            # 2014 back-references races/subraces; 2024 uses species/subspecies
            holders = []
            for key in ('races', 'subraces', 'species', 'subspecies'):
                holders += [r.get('name', '') for r in data.get(key) or []]
            db.session.add(tblTraitsLibrary(
                api_index   = index,
                name        = data['name'],
                races_text  = ', '.join(h for h in holders if h),
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Weapon properties sync ──────────────────────────────────────────────────────

def sync_weapon_properties_from_api(state=None):
    prop_list, err = merged_resource_list('weapon-properties')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(prop_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(prop_list):
        try:
            index = entry['index']
            if tblWeaponPropertiesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/weapon-properties/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            db.session.add(tblWeaponPropertiesLibrary(
                api_index   = index,
                name        = data['name'],
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Rules sync (rule categories + rule sections) ────────────────────────────────

def sync_rules_from_api(state=None):
    """SRD rules prose: /rules (6 chapters) gives grouping, /rule-sections (33)
    gives the actual text. Sections store their chapter as `parent`. 2014-only
    today; merged mode just finds nothing on 2024 and moves on."""
    section_parent = {}
    rules_list, _rules_err = merged_resource_list('rules')
    for entry, api_base in rules_list:
        try:
            detail = requests.get(f'{api_base}/rules/{entry["index"]}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            for sub in data.get('subsections', []):
                section_parent[sub.get('index')] = data.get('name', '')
        except Exception:
            continue

    sec_list, err = merged_resource_list('rule-sections')
    if err:
        return 0, 0, err
    if state is not None:
        state['total'] = len(sec_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(sec_list):
        try:
            index = entry['index']
            if tblRulesLibrary.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/rule-sections/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            db.session.add(tblRulesLibrary(
                api_index   = index,
                name        = data['name'],
                parent      = section_parent.get(index, ''),
                description = _desc_text(data),
                source      = 'srd',
                created_at  = _now(),
            ))
            db.session.commit()
            added += 1
        except Exception:
            db.session.rollback()
            errors += 1
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})
    return added, skipped, errors


# ── Subclasses library (browse, homebrew subclasses + their features) ───────────

@api.get('/subclasses')
def subclasses_library(q: str = '', cls: str = '', src: str = '', user=Depends(require_dm)):
    total = tblSubclassesLibrary.query.count()
    q, cls, src = q.strip(), cls.strip(), src.strip()
    subs = tblSubclassesLibrary.query
    if q:
        subs = subs.filter(tblSubclassesLibrary.name.ilike(f'%{q}%'))
    if cls:
        subs = subs.filter(tblSubclassesLibrary.class_name == cls)
    if src:
        subs = subs.filter(tblSubclassesLibrary.source == src)
    subs = subs.order_by(tblSubclassesLibrary.class_name, tblSubclassesLibrary.name).all()

    # features grouped per subclass name (lowercased) for the card expanders
    feats_by_sub = {}
    for f in (tblFeaturesLibrary.query
              .filter(tblFeaturesLibrary.subclass_name != '')
              .order_by(tblFeaturesLibrary.level, tblFeaturesLibrary.name).all()):
        feats_by_sub.setdefault(f.subclass_name.lower(), []).append(_row(f))

    class_names = [c.name for c in tblClassesLibrary.query.order_by(tblClassesLibrary.name).all()]
    return _page('subclasses', 'Subclasses Library', subs, total, {'q': q, 'cls': cls, 'src': src},
                 feats_by_sub=feats_by_sub, class_names=class_names)


@router.post('/subclasses/add')
def subclass_add(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    name       = _s(form, 'name')
    class_name = _s(form, 'class_name')
    if not name or not class_name:
        return _bad('Subclass name and class are both required.')
    if (tblSubclassesLibrary.query
            .filter(db.func.lower(tblSubclassesLibrary.name) == name.lower())
            .first()):
        return _bad(f'A subclass named "{name}" already exists.')
    sub = tblSubclassesLibrary(
        api_index   = None,
        name        = name,
        class_name  = class_name,
        flavor      = _s(form, 'flavor'),
        description = _s(form, 'description'),
        source      = 'homebrew',
        created_at  = _now(),
    )
    db.session.add(sub)
    db.session.commit()
    return {'ok': True, 'id': sub.subclass_lib_id,
            'message': (f'Added homebrew subclass "{name}" ({class_name}). Add its features below, '
                        f'then players can pick it on their sheet.')}


@router.post('/subclasses/{subclass_lib_id}/delete')
def subclass_delete(subclass_lib_id: int, user=Depends(require_dm)):
    sub = tblSubclassesLibrary.query.get_or_404(subclass_lib_id)
    if sub.source != 'homebrew':
        return _bad('Only homebrew subclasses can be deleted.')
    name = sub.name
    # its homebrew features go with it (SRD features are never touched)
    dropped = (tblFeaturesLibrary.query
               .filter(db.func.lower(tblFeaturesLibrary.subclass_name) == name.lower(),
                       tblFeaturesLibrary.source == 'homebrew')
               .delete(synchronize_session=False))
    db.session.delete(sub)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted "{name}"' + (f' and its {dropped} homebrew features.' if dropped else '.')}


@router.post('/subclasses/features/add')
def subclass_feature_add(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    sub = tblSubclassesLibrary.query.get_or_404(int(form.get('subclass_lib_id', 0) or 0))
    name = _s(form, 'name')
    if not name:
        return _bad('Feature name is required.')
    try:
        level = max(1, min(20, int(form.get('level', 1) or 1)))
    except (TypeError, ValueError):
        level = 1
    f = tblFeaturesLibrary(
        api_index     = None,
        name          = name,
        class_name    = sub.class_name,
        subclass_name = sub.name,
        level         = level,
        prerequisites = '',
        description   = _s(form, 'description'),
        source        = 'homebrew',
        created_at    = _now(),
    )
    db.session.add(f)
    db.session.commit()
    return {'ok': True, 'message': f'Added "{name}" (level {level}) to {sub.name}.', 'id': f.feature_lib_id}


@router.post('/features/{feature_lib_id}/delete')
def feature_delete(feature_lib_id: int, user=Depends(require_dm)):
    f = tblFeaturesLibrary.query.get_or_404(feature_lib_id)
    if f.source != 'homebrew':
        return _bad('Only homebrew features can be deleted.')
    name = f.name
    db.session.delete(f)
    db.session.commit()
    return {'ok': True, 'message': f'Deleted feature "{name}".'}


# ── Generic sync runner for the new libraries ────────────────────────────────────
# The classic libraries each grew a bespoke /X/sync route; the newer ones share
# one runner keyed by job type (same background-thread + _sync_states pattern,
# same /sync/status/<job_type> poller).

EXTRA_SYNCS = {
    'conditions':  sync_conditions_from_api,
    'magicitems':  sync_magic_items_from_api,
    'features':    sync_features_from_api,
    'classlevels': sync_class_levels_from_api,
    'subclasses':  sync_subclasses_from_api,
    'traits':      sync_traits_from_api,
    'weaponprops': sync_weapon_properties_from_api,
    'rules':       sync_rules_from_api,
}


# name/sub/desc lookups for the newer libraries — one generic search endpoint
# (used by the sheet's Reference tab) instead of a bespoke /X/search per type.
LOOKUP_MODELS = {
    'conditions':  (tblConditionsLibrary, lambda r: {
        'name': r.name, 'sub': '', 'desc': r.description or ''}),
    'magicitems':  (tblMagicItemsLibrary, lambda r: {
        'name': r.name,
        'sub': _join_sub([r.category or '', r.rarity or '',
                          'Requires attunement' if r.attunement else '']),
        'desc': r.description or ''}),
    'features':    (tblFeaturesLibrary, lambda r: {
        'name': r.name,
        'sub': _join_sub([r.class_name or '', r.subclass_name or '',
                          f'Level {r.level}' if r.level else '']),
        'desc': r.description or ''}),
    'subclasses':  (tblSubclassesLibrary, lambda r: {
        'name': r.name, 'sub': _join_sub([r.class_name or '', r.flavor or '']),
        'desc': r.description or ''}),
    'traits':      (tblTraitsLibrary, lambda r: {
        'name': r.name, 'sub': r.races_text or '', 'desc': r.description or ''}),
    'weaponprops': (tblWeaponPropertiesLibrary, lambda r: {
        'name': r.name, 'sub': '', 'desc': r.description or ''}),
    'rules':       (tblRulesLibrary, lambda r: {
        'name': r.name, 'sub': r.parent or '', 'desc': r.description or ''}),
}


@router.get('/lookup/{category}')
def reference_lookup(category: str, q: str = '', limit: str = '20', system: str = '', user=Depends(require_user)):
    entry = LOOKUP_MODELS.get(category)
    if entry is None:
        return JSONResponse([], status_code=404)
    model, to_dict = entry
    q = q.strip()
    try:
        lim = min(int(limit), 200)
    except ValueError:
        lim = 20
    query = model.query
    if q:
        query = query.filter(model.name.ilike(f'%{q}%'))
    if hasattr(model, 'game_system'):          # ?system=dcc|dnd5e|all (see _system_filter)
        query = _system_filter(query, model, system)
    rows = query.order_by(model.name).limit(lim).all()
    return [to_dict(r) for r in rows]


@router.post('/sync/run/{job_type}')
def sync_run(job_type: str, user=Depends(require_dm)):
    fn = EXTRA_SYNCS.get(job_type)
    if fn is None:
        return JSONResponse({'error': f'unknown sync job {job_type!r}'}, status_code=404)
    return start_sync_job(_sync_states, job_type, fn)


@router.get('/classes/search')
def classes_search(q: str = '', system: str = '', user=Depends(require_user)):
    q = q.strip()
    classes = _system_filter(tblClassesLibrary.query.filter(
        tblClassesLibrary.name.ilike(f'%{q}%')), tblClassesLibrary, system
    ).order_by(tblClassesLibrary.name).limit(500).all()
    return [{
        'class_lib_id':         c.class_lib_id,
        'name':                 c.name,
        'hit_die':              c.hit_die,
        'saving_throws':        c.saving_throws,
        'proficiencies':        c.proficiencies,
        'skill_choices':        c.skill_choices,
        'subclasses':           c.subclasses,
        'spellcasting_ability': c.spellcasting_ability,
        'description':          c.description,
        'game_system':          c.game_system or 'dnd5e',
    } for c in classes]


# ── Sync job table for the settings page's "Sync All" ──────────────────────────

SYNC_JOBS = [
    {'label': 'Monsters',  'job': 'monsters', 'syncUrl': '/ttrpg/monsters/sync', 'statusUrl': '/ttrpg/monsters/sync/status'},
] + [
    {'label': lbl, 'job': job, 'syncUrl': f'/ttrpg/reference/{job}/sync', 'statusUrl': f'/ttrpg/reference/sync/status/{job}'}
    for lbl, job in (('Feats', 'feats'), ('Weapons', 'weapons'), ('Armor', 'armor'), ('Spells', 'spells'),
                     ('Skills', 'skills'), ('Races', 'races'), ('Equipment', 'equipment'), ('Classes', 'classes'))
] + [
    {'label': lbl, 'job': job, 'syncUrl': f'/ttrpg/reference/sync/run/{job}', 'statusUrl': f'/ttrpg/reference/sync/status/{job}'}
    for lbl, job in (('Conditions', 'conditions'), ('Magic Items', 'magicitems'), ('Class Features', 'features'),
                     ('Class Levels', 'classlevels'), ('Subclasses', 'subclasses'), ('Traits', 'traits'),
                     ('Weapon Properties', 'weaponprops'), ('Rules', 'rules'))
]


@api.get('/sync-jobs')
def sync_jobs(user=Depends(require_dm)):
    return {'jobs': SYNC_JOBS}


open_router = api
