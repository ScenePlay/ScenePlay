"""Monsters & assets library (ported from routes/monsters.py): SRD monster
sync, search/detail, homebrew create/edit/delete/picture, add-to-session and
the session-monster instance controls the session page and battle-map tokens
call. JSON paths under /ttrpg/monsters keep their Flask shape; the library,
card and homebrew pages became /api/v1/monsters/... page data."""
import json
import math
import os
import re

import requests
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

import core.config as config
import integrations.relay_broadcaster as relay_broadcaster
from core.db import db
from models.ttrpg import tblBattleMaps, tblBattleMapTokens, tblMonsterTemplates, tblSessionMonsters, tblSessions
from routers._util import _now, form_or_json, json_body, save_upload_downscaled
from security.deps import require_dm, require_user
from ttrpg.ttrpg_common import CONDITIONS, condition_texts  # noqa: F401  (re-exported for callers)

router = APIRouter(prefix='/ttrpg/monsters')
api = APIRouter(prefix='/api/v1/monsters')

# Homebrew monster art lives here; SRD monsters use the dnd5eapi image instead.
MONSTER_IMG_DIR = os.path.join(config.UPLOADS_DIR, 'monsters')
MONSTER_IMG_EXTS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

_sync_states = {}


def _save_monster_image(file_storage):
    """Save an uploaded monster image (downscaled to token resolution) and
    return its root-relative /static URL, or None if there's no valid file.
    Caller decides what to do with it."""
    if file_storage is None or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in MONSTER_IMG_EXTS:
        return None
    fname = save_upload_downscaled(file_storage, MONSTER_IMG_DIR)
    return '/static/uploads/monsters/' + fname


def _existing_image_url(raw):
    """A picked existing picture as a root-relative /static/uploads URL,
    validated against the disk; '' when it is not one of ours."""
    import media.shared_assets as shared_assets
    raw = (raw or '').strip()
    m = re.match(r'^/static/uploads/([a-z]+)/([^/\\]+)$', raw)
    if not m or m.group(1) not in shared_assets.FOLDERS:
        return ''
    path = os.path.join(config.UPLOADS_DIR, m.group(1), m.group(2))
    return raw if os.path.isfile(path) else ''


def _drop_monster_image(old, template_id):
    """Delete a homebrew monster's own upload when it is replaced — unless
    another record points at the same file."""
    import media.shared_assets as shared_assets
    from extensions import database
    if not (isinstance(old, str) and old.startswith('/static/uploads/monsters/')):
        return
    name = os.path.basename(old)
    if shared_assets.referenced_elsewhere(database, 'monsters', name,
                                          exclude=('tblMonsterTemplates', 'template_id', template_id)):
        return
    try:
        os.remove(os.path.join(MONSTER_IMG_DIR, name))
    except OSError:
        pass


def _cr_display(cr):
    """Convert numeric CR to display string (0.5 → '1/2', 0.25 → '1/4')."""
    mapping = {0.125: '1/8', 0.25: '1/4', 0.5: '1/2'}
    try:
        f = float(cr)
        return mapping.get(f, str(int(f)) if f == int(f) else str(f))
    except (ValueError, TypeError):
        return str(cr)


def _cr_to_float(cr_str):
    """Convert stored CR text to float for range comparisons."""
    mapping = {'1/8': 0.125, '1/4': 0.25, '1/2': 0.5}
    if cr_str in mapping:
        return mapping[cr_str]
    try:
        return float(cr_str)
    except (ValueError, TypeError):
        return 0.0


def _extract_ac(armor_class):
    """Pull the first AC value from the API's armor_class list."""
    if isinstance(armor_class, list) and armor_class:
        return armor_class[0].get('value', 10)
    if isinstance(armor_class, int):
        return armor_class
    return 10


def _img_url(image):
    """SRD images are API-relative paths; homebrew ones are /static/ URLs."""
    if not image:
        return ''
    if image.startswith('http') or image.startswith('/static/') or image.startswith('data:'):
        return image
    return 'https://www.dnd5eapi.co' + image


# ── Sync all monsters from the SRD API ────────────────────────────────────────

def sync_monsters_from_api(state=None):
    from routers.reference import merged_resource_list
    monster_list, err = merged_resource_list('monsters')
    if err:
        return 0, 0, err

    if state is not None:
        state['total'] = len(monster_list)

    added = skipped = errors = 0
    for i, (entry, api_base) in enumerate(monster_list):
        try:
            index = entry['index']
            if tblMonsterTemplates.query.filter_by(api_index=index).first():
                skipped += 1
                continue
            detail = requests.get(f'{api_base}/monsters/{index}', timeout=10)
            detail.raise_for_status()
            data = detail.json()
            # The dedup .first() above opened a read transaction whose WAL
            # snapshot went stale during the HTTP call (background workers
            # commit every few seconds) — writing on it fails instantly with
            # "database is locked" (SQLITE_BUSY_SNAPSHOT). Start fresh.
            db.session.rollback()

            cr_raw = data.get('challenge_rating', 0)
            cr_str = _cr_display(cr_raw)

            t = tblMonsterTemplates(
                api_index    = index,
                name         = data.get('name', index),
                cr           = cr_str,
                monster_type = data.get('type', ''),
                size         = data.get('size', ''),
                hp_max       = data.get('hit_points', 0),
                ac           = _extract_ac(data.get('armor_class', [])),
                source       = 'srd',
                stats_json   = json.dumps(data),
                created_at   = _now(),
            )
            db.session.add(t)
            db.session.commit()
            added += 1
        except Exception:
            errors += 1
            # A failed flush/commit leaves the session in a rolled-back state
            # that would error every remaining iteration — clear it.
            try:
                db.session.rollback()
            except Exception:
                pass
        finally:
            if state is not None:
                state.update({'done': i + 1, 'added': added, 'skipped': skipped, 'errors': errors})

    return added, skipped, errors


# ── Library page ───────────────────────────────────────────────────────────────

@api.get('/page')
def library(user=Depends(require_dm)):
    from routers.reference import API_OPTIONS, api_label, get_api_base
    synced = tblMonsterTemplates.query.count()
    sessions = tblSessions.query.filter(
        tblSessions.status.in_(['planning', 'active'])
    ).order_by(tblSessions.title).all()
    raw_types = db.session.query(tblMonsterTemplates.monster_type).distinct().all()
    monster_types = sorted(t[0].lower() for t in raw_types if t[0])
    current_api = get_api_base()
    return {
        'synced': synced,
        'sessions': [{'session_id': s.session_id, 'title': s.title, 'status': s.status} for s in sessions],
        'conditions': condition_texts(),
        'monster_types': monster_types,
        'current_api': current_api,
        'api_label': api_label(current_api),
        'api_options': API_OPTIONS,
    }


# ── AJAX search ───────────────────────────────────────────────────────────────

@router.get('/search')
def search(q: str = '', type: str = '', size: str = '', source: str = '', cr_min: str = '', cr_max: str = '',
           limit: int = 50, user=Depends(require_dm)):
    q           = q.strip()
    type_filter = type.strip().lower()
    size_filter = size.strip()
    src_filter  = source.strip()
    limit       = min(int(limit), 500)

    query = tblMonsterTemplates.query

    if q:
        query = query.filter(tblMonsterTemplates.name.ilike(f'%{q}%'))
    if type_filter:
        query = query.filter(tblMonsterTemplates.monster_type.ilike(type_filter))
    if size_filter:
        query = query.filter(tblMonsterTemplates.size.ilike(size_filter))
    if src_filter in ('srd', 'homebrew'):
        query = query.filter(tblMonsterTemplates.source == src_filter)

    monsters = query.order_by(tblMonsterTemplates.name).all()

    if cr_min != '' or cr_max != '':
        cr_min_f = float(cr_min) if cr_min != '' else 0.0
        cr_max_f = float(cr_max) if cr_max != '' else 30.0
        monsters = [m for m in monsters if cr_min_f <= _cr_to_float(m.cr) <= cr_max_f]

    monsters = monsters[:limit]

    return [{
        'template_id': m.template_id,
        'name': m.name,
        'cr': m.cr,
        'type': m.monster_type,
        'size': m.size,
        'hp_max': m.hp_max,
        'ac': m.ac,
        'source': m.source,
    } for m in monsters]


# ── Monster detail (AJAX) ─────────────────────────────────────────────────────

@router.get('/{template_id}/detail')
def detail(template_id: int, user=Depends(require_dm)):
    m = tblMonsterTemplates.query.get_or_404(template_id)
    data = json.loads(m.stats_json or '{}')
    return {'ok': True, 'name': m.name, 'stats': data,
            'cr': m.cr, 'hp_max': m.hp_max, 'ac': m.ac,
            'source': m.source}


def _template_brief(m):
    return {'template_id': m.template_id, 'name': m.name, 'cr': m.cr, 'monster_type': m.monster_type,
            'size': m.size, 'hp_max': m.hp_max, 'ac': m.ac, 'source': m.source}


@api.get('/{template_id}/view-page')
def view_page(template_id: int, instance: int = None, user=Depends(require_dm)):
    """The monster card (templates/ttrpg/monster_detail.html). ?instance=<session
    monster id> (from a battle-map token double-click) surfaces THAT enemy's
    live HP controls + a dice roller on the card."""
    m = tblMonsterTemplates.query.get_or_404(template_id)
    stats = json.loads(m.stats_json or '{}')
    sm = None
    if instance:
        cand = db.session.get(tblSessionMonsters, instance)
        if cand is not None and cand.template_id == template_id:
            sm = cand
    # Proficiency bonus from CR (5e: +2 at CR 0-4, +1 per 4 CR after) for the
    # roller's PROF modifier button. CR is stored as text and may be '1/4'.
    try:
        cr_raw = m.cr or '0'
        if '/' in cr_raw:
            num, den = cr_raw.split('/', 1)
            cr_val = float(num) / float(den)
        else:
            cr_val = float(cr_raw)
    except (ValueError, ZeroDivisionError):
        cr_val = 0
    prof = max(2, 2 + (math.ceil(cr_val) - 1) // 4)
    return {
        'm': _template_brief(m), 'stats': stats,
        'image_url': _img_url(stats.get('image') or ''),
        'sm': ({'monster_id': sm.monster_id, 'display_name': sm.display_name, 'hp_current': sm.hp_current,
                'hp_max': sm.hp_max, 'hp_pct': sm.hp_pct(), 'session_id': sm.session_id} if sm else None),
        'prof': prof, 'game': tblSessions.active_game_info(),
    }


# ── Add to session ────────────────────────────────────────────────────────────

def _int_or_none(v):
    try:
        return int(v) if v not in (None, '') else None
    except (TypeError, ValueError):
        return None


@router.post('/{template_id}/add-to-session')
def add_to_session(template_id: int, form: dict = Depends(form_or_json), user=Depends(require_dm)):
    m = tblMonsterTemplates.query.get_or_404(template_id)
    session_id = _int_or_none(form.get('session_id'))
    count = max(1, min(20, _int_or_none(form.get('count')) or 1))
    hp_override = _int_or_none(form.get('hp_override'))

    if not session_id:
        return JSONResponse({'ok': False, 'error': 'No session selected'}, status_code=400)

    sess = tblSessions.query.get_or_404(session_id)
    existing_count = tblSessionMonsters.query.filter_by(
        session_id=session_id, template_id=template_id).count()

    hp = hp_override if hp_override and hp_override > 0 else m.hp_max

    created = []
    for i in range(count):
        num = existing_count + i + 1
        display = m.name if count == 1 and existing_count == 0 else f'{m.name} {num}'
        sm = tblSessionMonsters(
            session_id   = session_id,
            template_id  = template_id,
            display_name = display,
            hp_current   = hp,
            hp_max       = hp,
            ac           = m.ac,
            initiative   = 0,
            conditions   = '[]',
            is_alive     = 1,
            sort_order   = tblSessionMonsters.query.filter_by(session_id=session_id).count(),
        )
        db.session.add(sm)
        db.session.flush()
        created.append({'monster_id': sm.monster_id, 'display_name': display})

    db.session.commit()
    _emit_session(session_id)
    return {'ok': True, 'created': created, 'session_title': sess.title}


def _emit_session(session_id):
    import core.events as events
    if session_id:
        events.emit(f'session:{session_id}', {'monsters': True})


# ── Sync trigger ──────────────────────────────────────────────────────────────

@router.post('/sync')
def sync(user=Depends(require_dm)):
    from routers.reference import start_sync_job
    return start_sync_job(_sync_states, 'monsters', sync_monsters_from_api)


@router.get('/sync/status')
def sync_status(user=Depends(require_user)):
    state = _sync_states.get('monsters', {})
    if not state:
        return {'running': False, 'total': 0, 'done': 0, 'message': ''}
    return dict(state)


# ── Homebrew create / edit ────────────────────────────────────────────────────

def _int(form, key, default):
    try:
        return int(form.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _str(form, key, default=''):
    v = form.get(key, default)
    return default if v is None else str(v)


def _stats_from_form(form, name):
    return {
        'name': name,
        'size': _str(form, 'size'),
        'type': _str(form, 'monster_type'),
        'alignment': _str(form, 'alignment'),
        'hit_points': _int(form, 'hp_max', 0),
        'armor_class': [{'value': _int(form, 'ac', 10), 'type': 'natural'}],
        'speed': {'walk': _str(form, 'speed', '30 ft.')},
        'strength': _int(form, 'str_val', 10),
        'dexterity': _int(form, 'dex_val', 10),
        'constitution': _int(form, 'con_val', 10),
        'intelligence': _int(form, 'int_val', 10),
        'wisdom': _int(form, 'wis_val', 10),
        'charisma': _int(form, 'cha_val', 10),
        'challenge_rating': _str(form, 'cr', '0'),
        'xp': _int(form, 'xp', 0),
        'languages': _str(form, 'languages'),
        'notes': _str(form, 'notes'),
    }


def _homebrew_page(m=None, stats=None):
    from ttrpg.genre_packs import icon_prompt_client_data
    return {'m': _template_brief(m) if m else None, 'stats': stats or {},
            'icon_genres': icon_prompt_client_data()}


@api.get('/homebrew/new')
def homebrew_new_page(user=Depends(require_dm)):
    return _homebrew_page()


@api.get('/homebrew/{template_id}')
def homebrew_edit_page(template_id: int, user=Depends(require_dm)):
    m = tblMonsterTemplates.query.get_or_404(template_id)
    if m.source != 'homebrew':
        return {'redirect': '/ttrpg/monsters', 'message': 'Only homebrew monsters can be edited.'}
    return _homebrew_page(m, json.loads(m.stats_json or '{}'))


@router.post('/homebrew/new')
def homebrew_new(form: dict = Depends(form_or_json), image: UploadFile = File(None), user=Depends(require_dm)):
    name = _str(form, 'name').strip()
    if not name:
        return JSONResponse({'ok': False, 'error': 'Monster name is required.'}, status_code=400)
    stats = _stats_from_form(form, name)
    stats.update({'senses': {}, 'special_abilities': [], 'actions': []})
    img_url = (_save_monster_image(image)
               or _existing_image_url(_str(form, 'image_ref')))
    if img_url:
        stats['image'] = img_url
    t = tblMonsterTemplates(
        api_index    = None,
        name         = name,
        cr           = _str(form, 'cr', '0'),
        monster_type = _str(form, 'monster_type'),
        size         = _str(form, 'size'),
        hp_max       = _int(form, 'hp_max', 0),
        ac           = _int(form, 'ac', 10),
        source       = 'homebrew',
        stats_json   = json.dumps(stats),
        created_at   = _now(),
    )
    db.session.add(t)
    db.session.commit()
    return {'ok': True, 'message': f'Homebrew entry "{name}" created.', 'template_id': t.template_id}


@router.get('/homebrew/random')
def homebrew_random(kind: str = 'monster', genre: str = 'fantasy', tier: str = 'standard', user=Depends(require_dm)):
    """Roll a complete homebrew entry (monster / vehicle / asset) as JSON for
    the homebrew form to fill in."""
    from ttrpg.homebrew_randgen import generate_homebrew
    return generate_homebrew(kind=kind, genre=genre, tier=tier)


@router.post('/homebrew/{template_id}/edit')
def homebrew_edit(template_id: int, form: dict = Depends(form_or_json), image: UploadFile = File(None),
                  user=Depends(require_dm)):
    m = tblMonsterTemplates.query.get_or_404(template_id)
    if m.source != 'homebrew':
        return JSONResponse({'ok': False, 'error': 'Only homebrew monsters can be edited.'}, status_code=400)
    name = _str(form, 'name').strip()
    if not name:
        return JSONResponse({'ok': False, 'error': 'Monster name is required.'}, status_code=400)
    stats = json.loads(m.stats_json or '{}')
    # Update editable fields, PRESERVING anything the form doesn't cover
    # (image, special_abilities, actions, senses stay intact).
    stats.update(_stats_from_form(form, name))
    # Optional new picture (replaces the previous local upload, if any).
    new_img = (_save_monster_image(image)
               or _existing_image_url(_str(form, 'image_ref')))
    if new_img:
        _drop_monster_image(stats.get('image', ''), m.template_id)
        stats['image'] = new_img

    m.name         = name
    m.cr           = _str(form, 'cr', '0')
    m.monster_type = _str(form, 'monster_type')
    m.size         = _str(form, 'size')
    m.hp_max       = _int(form, 'hp_max', 0)
    m.ac           = _int(form, 'ac', 10)
    m.stats_json   = json.dumps(stats)
    db.session.commit()
    return {'ok': True, 'message': f'Homebrew entry "{name}" updated.', 'template_id': m.template_id}


@router.post('/homebrew/{template_id}/image')
def homebrew_image(template_id: int, form: dict = Depends(form_or_json), image: UploadFile = File(None),
                   user=Depends(require_dm)):
    """Set / replace the picture on an existing homebrew monster."""
    m = tblMonsterTemplates.query.get_or_404(template_id)
    if m.source != 'homebrew':
        return JSONResponse({'ok': False, 'error': 'Only homebrew monsters can have a custom image.'}, status_code=400)
    img_url = (_save_monster_image(image)
               or _existing_image_url(form.get('image_url') or form.get('image_ref')))
    if not img_url:
        return JSONResponse({'ok': False, 'error': 'No valid image (png/jpg/gif/webp).'}, status_code=400)
    stats = json.loads(m.stats_json or '{}')
    _drop_monster_image(stats.get('image', ''), m.template_id)
    stats['image'] = img_url
    m.stats_json = json.dumps(stats)
    db.session.commit()
    return {'ok': True, 'image_url': img_url}


@router.post('/homebrew/{template_id}/delete')
def homebrew_delete(template_id: int, user=Depends(require_dm)):
    m = tblMonsterTemplates.query.get_or_404(template_id)
    if m.source != 'homebrew':
        return JSONResponse({'ok': False, 'error': 'Cannot delete SRD monsters.'}, status_code=400)
    # instances point at the template (NOT NULL FK): the Flask route crashed here
    n_inst = tblSessionMonsters.query.filter_by(template_id=template_id).count()
    if n_inst:
        return JSONResponse({'ok': False, 'error': f'"{m.name}" is still in a session ({n_inst} instance(s)) — remove it from the session first.'},
                            status_code=400)
    name = m.name
    db.session.delete(m)
    db.session.commit()
    return {'ok': True, 'message': f'"{name}" deleted.'}


# ── Session monster instance controls (AJAX) ──────────────────────────────────

def _hp_reply(sm):
    return {'ok': True, 'hp_current': sm.hp_current, 'hp_pct': sm.hp_pct(), 'is_alive': sm.is_alive}


def _broadcast_health(sm):
    token_id = relay_broadcaster.find_token_id('monster', sm.monster_id)
    if token_id:
        relay_broadcaster.broadcast_token_health(token_id, sm.hp_current, sm.hp_max)
    _emit_session(sm.session_id)


@router.post('/instance/{monster_id}/hp')
def instance_hp(monster_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    delta = int(data.get('delta', 0) or 0)
    sm.hp_current = max(0, min(sm.hp_max, sm.hp_current + delta))
    if sm.hp_current == 0:
        sm.is_alive = 0
    db.session.commit()
    _broadcast_health(sm)
    return _hp_reply(sm)


@router.post('/instance/{monster_id}/hp-set')
def instance_hp_set(monster_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    sm.hp_current = max(0, min(sm.hp_max, int(data.get('hp', sm.hp_current))))
    sm.is_alive = 0 if sm.hp_current == 0 else 1
    db.session.commit()
    _broadcast_health(sm)
    return _hp_reply(sm)


@router.post('/instance/{monster_id}/initiative')
def instance_initiative(monster_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    sm.initiative = int(data.get('initiative', 0) or 0)
    db.session.commit()
    _emit_session(sm.session_id)
    return {'ok': True, 'initiative': sm.initiative}


@router.post('/instance/{monster_id}/condition')
def instance_condition(monster_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    condition = str(data.get('condition', '') or '').strip()
    action = data.get('action', 'add')  # 'add' or 'remove'
    conds = json.loads(sm.conditions or '[]')
    if action == 'add' and condition and condition not in conds:
        conds.append(condition)
    elif action == 'remove' and condition in conds:
        conds.remove(condition)
    sm.conditions = json.dumps(conds)
    db.session.commit()
    tok_id = relay_broadcaster.find_token_id('monster', monster_id)
    if tok_id is not None:
        relay_broadcaster.broadcast_condition_update(conds, token_id=tok_id)
    _emit_session(sm.session_id)
    return {'ok': True, 'conditions': conds}


@router.post('/instance/{monster_id}/revive')
def instance_revive(monster_id: int, user=Depends(require_dm)):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    sm.is_alive = 1
    sm.hp_current = sm.hp_max
    db.session.commit()
    _broadcast_health(sm)
    return {'ok': True}


@router.post('/instance/{monster_id}/delete')
def instance_delete(monster_id: int, user=Depends(require_dm)):
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    session_id = sm.session_id
    # Remove any battlemap tokens for this monster too, so it doesn't linger as an
    # orphan (blank) token on the relay after the monster itself is gone.
    tok_rows = tblBattleMapTokens.query.filter_by(
        entity_type='monster', entity_id=monster_id).all()
    affected_map_ids = {tr.map_id for tr in tok_rows}
    for tr in tok_rows:
        db.session.delete(tr)
    db.session.delete(sm)
    db.session.commit()
    # Refresh the relay for any affected live map so the token disappears at once
    # (rather than on the next unrelated map push).
    try:
        from routers.battlemap import _push_map_state
        for mid in affected_map_ids:
            bm = db.session.get(tblBattleMaps, mid)
            if bm:
                _push_map_state(bm)
    except Exception:
        pass
    _emit_session(session_id)
    return {'ok': True}


open_router = api
