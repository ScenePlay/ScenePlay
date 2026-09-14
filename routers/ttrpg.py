"""TTRPG core (ported from routes/ttrpg.py): dashboard/characters/sessions
page data, the character sheet's inline edits, sub-item CRUD, dice, sessions
and session notes. JSON paths under /ttrpg keep their Flask shape; the old
render_template pages became /api/v1/... page-data endpoints."""
import json as _json
import os
import random
from datetime import datetime

from fastapi import APIRouter, Depends, File, Request, UploadFile

import core.config as config
import ttrpg.dice_systems as dice_systems
import core.events as events
import integrations.relay_broadcaster as relay_broadcaster
from core.db import db
from models.campaigns import tblcampaigns
from models.scenes import tblscenes
from models.ttrpg import (tblCharacterArmor, tblCharacterConditions, tblCharacterFeats,
                          tblCharacterInventory, tblCharacterNotes, tblCharacterResources,
                          tblCharacterSkills, tblCharacterSpells, tblCharacterWeapons, tblCharacters,
                          tblClassLevelsLibrary, tblClassesLibrary, tblDiceRolls, tblFeaturesLibrary,
                          tblRacesLibrary, tblSessionNotes, tblSessionParty, tblSessions)
from models.ttrpg import tblSessionMonsters as _tblSessionMonsters
from routers._util import _now, form_or_json, json_body, save_upload_downscaled
from security.deps import ApiError, get_current_user, require_dm, require_user
from ttrpg.ttrpg_common import condition_texts

router = APIRouter(prefix='/ttrpg')
api = APIRouter(prefix='/api/v1')

PORTRAIT_FOLDER = os.path.join(config.UPLOADS_DIR, 'portraits')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}


# ── helpers ───────────────────────────────────────────────────────────────────

def active_game_info():
    return tblSessions.active_game_info()


def _game_fields_from(src):
    sys_id = (src.get('game_system') or dice_systems.DEFAULT_SYSTEM).strip()
    if sys_id not in dice_systems.SYSTEMS:
        sys_id = dice_systems.DEFAULT_SYSTEM
    raw = {}
    if src.get('floor') not in (None, ''):
        raw['floor'] = src.get('floor')
    for k in ('collapse_at', 'collapse_note'):
        if k in src and src[k] is not None:
            raw[k] = src[k]
    return sys_id, _json.dumps(dice_systems.normalize_settings(sys_id, raw))


def _dcc_fields_from(src, base=None):
    return dice_systems.dcc_merge_fields(src, base)


def _dcc_pairing_warning(char):
    if char is None or not getattr(char, 'is_dcc', False) or not (char.race and char.char_class):
        return ''
    cls = tblClassesLibrary.query.filter(db.func.lower(tblClassesLibrary.name) == char.char_class.strip().lower(),
                                         tblClassesLibrary.game_system == 'dcc').first()
    race = tblRacesLibrary.query.filter(db.func.lower(tblRacesLibrary.name) == char.race.strip().lower(),
                                        tblRacesLibrary.game_system == 'dcc').first()
    if cls and race and 'Earth Class' in (cls.description or '') and (race.description or '').startswith('Alien Race'):
        return f'{cls.name} is an Earth Class, but {race.name} is an Alien Race — Alien Races cannot take Earth Classes (p.128).'
    return ''


def _systems():
    return {sid: {'name': gs['name']} for sid, gs in dice_systems.SYSTEMS.items()}


def _sheet_context(char):
    return {
        'dcc_pairing_warning': _dcc_pairing_warning(char),
        'game': active_game_info(),
        'game_systems': _systems(),
        'dcc': char.dcc() if char is not None else dice_systems.dcc_defaults(),
        'dcc_debuffs': dice_systems.DCC_DEBUFFS,
        'dcc_stat_names': dice_systems.DCC_STAT_NAMES,
        'dcc_skill_categories': list(dice_systems.DCC_SKILL_CATEGORIES),
        'dcc_sizes': [list(x) for x in dice_systems.DCC_SIZES],
    }


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def _drop_portrait(char):
    import media.shared_assets as shared_assets
    from extensions import database
    name = char.portrait_path
    if not name or shared_assets.is_ref(name):
        return
    if shared_assets.referenced_elsewhere(database, 'portraits', name,
                                          exclude=('tblCharacters', 'character_id', char.character_id)):
        return
    old = os.path.join(PORTRAIT_FOLDER, name)
    if os.path.exists(old):
        os.remove(old)


def _portrait_ref(form):
    import media.shared_assets as shared_assets
    from extensions import database
    ref = (form.get('portrait_ref') or '').strip()
    if ref and shared_assets.valid_ref(config.ROOT, database, 'portraits', ref, kinds=('image',)):
        return ref
    return ''


def _can_edit(user, char):
    return user.is_dm() or char.user_id == user.user_id


def _own_or_403(user, char):
    if not _can_edit(user, char):
        raise ApiError(403, 'forbidden', code='forbidden')


def portrait_url(char):
    if not char.portrait_path:
        return ''
    import media.shared_assets as shared_assets
    p = char.portrait_path
    if shared_assets.is_ref(p):
        try:
            return shared_assets.display_url(p) if hasattr(shared_assets, 'display_url') else '/static/uploads/portraits/' + p
        except Exception:
            return '/static/uploads/portraits/' + p
    return '/static/uploads/portraits/' + p


def _hp_color(pct):
    return '#28a745' if pct > 50 else ('#ffc107' if pct > 20 else '#dc3545')


def char_brief(c):
    return {
        'character_id': c.character_id, 'name': c.name, 'char_class': c.char_class or '', 'subclass': c.subclass or '',
        'race': c.race or '', 'level': c.level, 'background': c.background or '', 'genre': c.genre or 'fantasy',
        'hp_current': c.hp_current, 'hp_max': c.hp_max, 'hp_pct': c.hp_pct(), 'hp_color': _hp_color(c.hp_pct()),
        'ac': c.ac, 'is_dcc': c.is_dcc, 'dr_total': c.dr_total() if c.is_dcc else None,
        'user_id': c.user_id, 'user_display_name': c.user.display_name if c.user else '',
        'portrait_path': c.portrait_path or '', 'portrait_url': portrait_url(c),
        'game_system': c.game_system or 'dnd5e', 'has_feed': c.has_feed(),
        'conditions': [x.condition_name for x in c.conditions],
        'skills': [{'skill_id': s.skill_id, 'skill_name': s.skill_name, 'bonus': s.bonus, 'proficient': s.proficient,
                    'category': s.category or '', 'stat': s.stat or '', 'order_by': s.order_by}
                   for s in sorted(c.skills, key=lambda s: (s.order_by or 0))],
    }


def char_full(c):
    """Everything the character sheet template read off `char`."""
    d = char_brief(c)
    d.update({k: getattr(c, k) for k in ('str_val', 'dex_val', 'con_val', 'int_val', 'wis_val', 'cha_val', 'speed',
                                          'initiative_bonus', 'passive_perception', 'gold', 'silver', 'copper',
                                          'active', 'created_at', 'video_stream_id', 'video_feed_url')})
    d['stat_keys'] = c.stat_keys()
    d['scores'] = {k: c.score(k) for k in tblCharacters.STAT_KEYS}
    d['enhanced'] = {k: c.enhanced(k) for k in tblCharacters.STAT_KEYS}
    d['stat_mods'] = {k: c.stat_mod(k) for k in tblCharacters.STAT_KEYS}
    d['modifiers'] = {k: c.modifier(c.score(k)) for k in tblCharacters.STAT_KEYS}
    d['dcc'] = c.dcc()
    d['hb_slot_value'] = c.hb_slot_value() if c.is_dcc else None
    d['mana_max'] = c.mana_max() if c.is_dcc else None
    d['evade_bonus'] = c.evade_bonus() if c.is_dcc else None
    d['resources'] = [{'resource_id': r.resource_id, 'resource_name': r.resource_name, 'current_val': r.current_val,
                       'max_val': r.max_val, 'order_by': r.order_by} for r in sorted(c.resources, key=lambda r: (r.order_by or 0))]
    d['condition_rows'] = [{'condition_id': x.condition_id, 'condition_name': x.condition_name, 'notes': x.notes or ''}
                           for x in c.conditions]
    d['inventory'] = [{'item_id': i.item_id, 'item_name': i.item_name, 'quantity': i.quantity, 'weight': i.weight or '',
                       'notes': i.notes or '', 'equipped': i.equipped, 'hotlist': i.hotlist, 'order_by': i.order_by}
                      for i in sorted(c.inventory, key=lambda i: (i.order_by or 0))]
    d['notes'] = [{'note_id': n.note_id, 'note_text': n.note_text, 'created_at': n.created_at} for n in c.notes]
    d['feats'] = [{'feat_id': f.feat_id, 'feat_name': f.feat_name, 'description': f.description or '', 'order_by': f.order_by}
                  for f in sorted(c.feats, key=lambda f: (f.order_by or 0))]
    d['armor'] = [{'char_armor_id': a.char_armor_id, 'armor_lib_id': a.armor_lib_id, 'armor_name': a.armor_name,
                   'armor_category': a.armor_category or '', 'armor_class_base': a.armor_class_base, 'dex_bonus': a.dex_bonus,
                   'max_dex_bonus': a.max_dex_bonus, 'ac_bonus': a.ac_bonus, 'equipped': a.equipped, 'notes': a.notes or '',
                   'order_by': a.order_by} for a in sorted(c.armor, key=lambda a: (a.order_by or 0))]
    d['weapons'] = [{'char_weapon_id': w.char_weapon_id, 'weapon_lib_id': w.weapon_lib_id, 'weapon_name': w.weapon_name,
                     'weapon_category': w.weapon_category or '', 'weapon_range': w.weapon_range or '',
                     'damage_dice': w.damage_dice or '', 'damage_type': w.damage_type or '',
                     'two_handed_damage_dice': w.two_handed_damage_dice or '', 'two_handed_damage_type': w.two_handed_damage_type or '',
                     'range_normal': w.range_normal, 'range_long': w.range_long, 'attack_bonus': w.attack_bonus,
                     'damage_bonus': w.damage_bonus, 'properties': w.properties or '', 'equipped': w.equipped,
                     'notes': w.notes or '', 'order_by': w.order_by} for w in sorted(c.weapons, key=lambda w: (w.order_by or 0))]
    d['spells'] = [{'char_spell_id': s.char_spell_id, 'spell_lib_id': s.spell_lib_id, 'spell_name': s.spell_name,
                    'spell_level': s.spell_level, 'school': s.school or '', 'prepared': s.prepared, 'notes': s.notes or '',
                    'order_by': s.order_by,
                    'lib': ({'casting_time': s.lib_spell.casting_time, 'range_text': s.lib_spell.range_text,
                             'components': s.lib_spell.components, 'duration': s.lib_spell.duration,
                             'concentration': s.lib_spell.concentration, 'ritual': s.lib_spell.ritual,
                             'description': s.lib_spell.description, 'damage_dice': s.lib_spell.damage_dice,
                             'damage_type': s.lib_spell.damage_type, 'classes_text': s.lib_spell.classes_text}
                            if s.lib_spell else None)}
                   for s in sorted(c.spells, key=lambda s: (s.spell_level or 0, s.order_by or 0))]
    return d


def session_brief(s):
    return {'session_id': s.session_id, 'title': s.title, 'session_number': s.session_number,
            'campaign_id': s.campaign_id, 'campaign_name': s.campaign.campaign_name if s.campaign else None,
            'status': s.status, 'session_date': s.session_date or '', 'created_at': s.created_at,
            'party_ids': [sp.character_id for sp in s.party], 'party_count': len(s.party),
            'game': s.game_info()}


# ── relay push of touched characters (the old after_flush + after_request pair) ──

_RELAY_CHAR_SUBITEMS = (tblCharacterResources, tblCharacterConditions, tblCharacterInventory, tblCharacterSkills,
                        tblCharacterNotes, tblCharacterFeats, tblCharacterArmor, tblCharacterWeapons, tblCharacterSpells)


def _relay_collect_chars(session, flush_context):
    import core.db as _dbmod
    if _dbmod._request_scope.get() is None:
        return
    try:
        ids = session.info.setdefault('_relay_char_ids', set())
        for obj in set(session.new) | set(session.dirty) | set(session.deleted):
            if isinstance(obj, tblCharacters):
                if obj.character_id:
                    ids.add(obj.character_id)
            elif isinstance(obj, _RELAY_CHAR_SUBITEMS):
                cid = getattr(obj, 'character_id', None)
                if cid:
                    ids.add(cid)
    except Exception:
        pass


from sqlalchemy import event as _sa_event   # noqa: E402
_sa_event.listen(db.session, 'after_flush', _relay_collect_chars)


def push_dirty_chars_after():
    """Router-level dependency: after the handler returns (commit done), push
    every character the request touched. Best-effort."""
    yield
    try:
        ids = db.session.info.pop('_relay_char_ids', None)
        for cid in ids or ():
            try:
                char = db.session.get(tblCharacters, cid)
                if char is not None:
                    relay_broadcaster.push_character_and_broadcast(char)
                    events.emit(f'character:{cid}', {'character_id': cid})
            except Exception:
                pass
    except Exception:
        pass


router.dependencies.append(Depends(push_dirty_chars_after))
api.dependencies.append(Depends(push_dirty_chars_after))


# ── page data ─────────────────────────────────────────────────────────────────

@api.get('/ttrpg/dashboard')
def dashboard(user=Depends(require_user)):
    if not user.is_dm():
        return {'redirect': '/ttrpg/my-character'}
    campaigns = tblcampaigns.query.order_by(tblcampaigns.campaign_name).all()
    sessions = tblSessions.query.order_by(tblSessions.created_at.desc()).all()
    characters = tblCharacters.query.filter_by(active=1).order_by(tblCharacters.name).all()
    active_session = tblSessions.query.filter_by(status='active').first()
    camp_chars = {}
    for cid, chid in (db.session.query(tblSessions.campaign_id, tblSessionParty.character_id)
                      .join(tblSessionParty, tblSessionParty.session_id == tblSessions.session_id)
                      .filter(tblSessions.campaign_id.isnot(None)).distinct().all()):
        camp_chars.setdefault(cid, set()).add(chid)
    return {
        'campaigns': [{'campaign_id': c.campaign_id, 'campaign_name': c.campaign_name, 'active': c.active,
                       'char_ids': sorted(camp_chars.get(c.campaign_id, set()))} for c in campaigns],
        'sessions': [session_brief(s) for s in sessions],
        'characters': [char_brief(c) for c in characters],
        'active_session': session_brief(active_session) if active_session else None,
    }


@api.get('/characters')
def characters_list(scope: str = 'mine', all: int = 0, user=Depends(require_user)):
    from sql import appsettingGet
    if scope == 'all':
        if not user.is_dm():
            raise ApiError(403, 'DM only', code='dm_required')
        chars = tblCharacters.query.filter_by(active=1).order_by(tblCharacters.name).all()
        sessions = tblSessions.query.order_by(tblSessions.created_at.desc()).all()
        active_session = tblSessions.query.filter_by(status='active').first()
        sess_chars = {}
        for sid, chid in db.session.query(tblSessionParty.session_id, tblSessionParty.character_id).distinct().all():
            sess_chars.setdefault(sid, set()).add(chid)
        return {'characters': [char_brief(c) for c in chars],
                'sessions': [dict(session_brief(s), char_ids=sorted(sess_chars.get(s.session_id, set()))) for s in sessions],
                'active_session_id': active_session.session_id if active_session else None}
    # mine
    from models.ttrpg import tblBattleMaps
    chars = tblCharacters.query.filter_by(user_id=user.user_id, active=1).order_by(tblCharacters.name).all()
    active_map = None
    active_session = tblSessions.query.filter_by(status='active').first()
    if active_session:
        active_map = tblBattleMaps.query.filter_by(session_id=active_session.session_id, is_active=1).first()
    hidden_count = 0
    show_all = bool(all)
    campaign_name = ''
    if active_session and not show_all:
        party_ids = {sp.character_id for sp in active_session.party}
        in_session = [c for c in chars if c.character_id in party_ids]
        hidden_count = len(chars) - len(in_session)
        chars = in_session
        if active_session.campaign_id:
            camp = db.session.get(tblcampaigns, active_session.campaign_id)
            campaign_name = camp.campaign_name if camp else ''
    return {'characters': [char_brief(c) for c in chars],
            'active_map': {'map_id': active_map.map_id, 'name': active_map.name} if active_map else None,
            'hidden_count': hidden_count, 'show_all': show_all, 'campaign_name': campaign_name,
            'obs_enabled': appsettingGet('obs_enabled', '0') == '1'}


@router.get('/character/random')
def character_random(system: str = None, floor: str = None, min_level: int = 1, max_level: int = 20,
                     genre: str = 'fantasy', user=Depends(require_user)):
    if system == 'dcc':
        import ttrpg.dcc_randgen as dcc_randgen
        fl = 'third' if floor == 'third' else 'first'
        races = tblRacesLibrary.query.filter_by(game_system='dcc').all()
        classes = tblClassesLibrary.query.filter_by(game_system='dcc').all()
        return dcc_randgen.generate_crawler(fl, races=races, classes=classes)
    from ttrpg.char_randgen import generate_character
    return generate_character(min_level, max_level, genre=genre)


@api.get('/characters/new-options')
def character_new_options(user=Depends(require_user)):
    from ttrpg.genre_packs import client_data, genre_labels
    open_sessions = (tblSessions.query.filter(tblSessions.status.in_(['planning', 'active']))
                     .order_by(tblSessions.created_at.desc()).all()) if user.is_dm() else []
    return {**_sheet_context(None), 'genre_options': [list(x) for x in genre_labels()],
            'genre_client_data': client_data(),
            'open_sessions': [{'session_id': s.session_id, 'title': s.title, 'status': s.status} for s in open_sessions]}


def _int(form, key, default=0):
    try:
        v = form.get(key, default)
        return int(v if v not in (None, '') else default)
    except (TypeError, ValueError):
        return int(default or 0)


@api.post('/characters')
def character_create(form: dict = Depends(form_or_json), portrait: UploadFile = File(None), user=Depends(require_user)):
    name = (form.get('name') or '').strip()
    if not name:
        raise ApiError(400, 'Character name is required.')
    char = tblCharacters(
        user_id=user.user_id, name=name,
        char_class=(form.get('char_class') or '').strip(), subclass=(form.get('subclass') or '').strip(),
        race=(form.get('race') or '').strip(), level=_int(form, 'level', 1) or 1,
        background=(form.get('background') or '').strip(), genre=(form.get('genre') or 'fantasy').strip() or 'fantasy',
        hp_max=_int(form, 'hp_max', 0), hp_current=_int(form, 'hp_max', 0), ac=_int(form, 'ac', 10) or 10,
        str_val=_int(form, 'str_val', 10) or 10, dex_val=_int(form, 'dex_val', 10) or 10, con_val=_int(form, 'con_val', 10) or 10,
        int_val=_int(form, 'int_val', 10) or 10, wis_val=_int(form, 'wis_val', 10) or 10, cha_val=_int(form, 'cha_val', 10) or 10,
        speed=_int(form, 'speed', 30) or 30, initiative_bonus=_int(form, 'initiative_bonus', 0),
        passive_perception=_int(form, 'passive_perception', 10) or 10,
        gold=_int(form, 'gold', 0), silver=_int(form, 'silver', 0), copper=_int(form, 'copper', 0),
        active=1, created_at=_now(),
    )
    gs = (form.get('game_system') or active_game_info()['id']).strip()
    char.game_system = gs if gs in dice_systems.SYSTEMS else dice_systems.DEFAULT_SYSTEM
    if char.is_dcc:
        char.dcc_json = _json.dumps(_dcc_fields_from(form))
        char.hp_max = dice_systems.DCC_HB_SLOTS
        char.hp_current = dice_systems.DCC_HB_SLOTS
    db.session.add(char)
    db.session.flush()
    if char.is_dcc:
        db.session.add(tblCharacterResources(character_id=char.character_id, resource_name='Mana',
                                             current_val=char.mana_max(), max_val=char.mana_max(), order_by=0))
        try:
            r_skills = _json.loads(form.get('dcc_skills_json') or '[]')
            r_items = _json.loads(form.get('dcc_items_json') or '[]')
            r_applied = _json.loads(form.get('dcc_applied_json') or '[]')
        except ValueError:
            r_skills, r_items, r_applied = [], [], []
        for i, sk in enumerate(r_skills[:40]):
            if not isinstance(sk, dict) or not str(sk.get('name', '')).strip():
                continue
            db.session.add(tblCharacterSkills(
                character_id=char.character_id, skill_name=str(sk['name'])[:60],
                bonus=max(0, min(20, int(sk.get('rank', 1) or 1))), proficient=1,
                category=str(sk.get('category', ''))[:20], stat=str(sk.get('stat', ''))[:5], order_by=i))
        for i, it in enumerate(r_items[:30]):
            if not str(it).strip():
                continue
            db.session.add(tblCharacterInventory(character_id=char.character_id, item_name=str(it)[:120], quantity=1,
                                                 weight='', notes='', equipped=0, order_by=i))
        if r_applied:
            bag = char.dcc()
            bag['applied'] = [str(a)[:80] for a in r_applied if isinstance(a, str)][:4]
            char.dcc_json = _json.dumps(bag)
    added_to_session = None
    add_sid = str(form.get('add_session_id') or '').strip()
    if add_sid.isdigit() and user.is_dm():
        sess = db.session.get(tblSessions, int(add_sid))
        if sess and sess.status in ('planning', 'active'):
            db.session.add(tblSessionParty(session_id=sess.session_id, character_id=char.character_id, joined_at=_now()))
            added_to_session = sess
    traits_note = (form.get('traits_note') or '').strip()
    if traits_note:
        db.session.add(tblCharacterNotes(character_id=char.character_id, note_text=traits_note, created_at=_now()))
    if portrait and portrait.filename and _allowed_file(portrait.filename):
        char.portrait_path = save_upload_downscaled(portrait, PORTRAIT_FOLDER)
    elif _portrait_ref(form):
        char.portrait_path = _portrait_ref(form)
    db.session.commit()
    msg = ''
    if added_to_session:
        relay_broadcaster.push_all_characters()
        msg = f'"{char.name}" added to session #{added_to_session.session_number} {added_to_session.title}.'
    return {'ok': True, 'character_id': char.character_id, 'message': msg}


# ── class progression ─────────────────────────────────────────────────────────

_CLASS_RESOURCE_NAMES = {
    'rage_count': 'Rages', 'ki_points': 'Ki Points', 'sorcery_points': 'Sorcery Points',
    'channel_divinity_charges': 'Channel Divinity', 'action_surges': 'Action Surge', 'indomitable_uses': 'Indomitable',
}


def _class_progression(char):
    from sqlalchemy import func, or_
    cls = (char.char_class or '').strip()
    if not cls:
        return [], None
    sub = (getattr(char, 'subclass', '') or '').strip()
    feat_filter = (func.lower(tblFeaturesLibrary.class_name) == cls.lower())
    if sub:
        subclass_match = or_(tblFeaturesLibrary.subclass_name == '',
                             func.lower(tblFeaturesLibrary.subclass_name) == sub.lower())
    else:
        subclass_match = (tblFeaturesLibrary.subclass_name == '')
    features = (tblFeaturesLibrary.query.filter(feat_filter, subclass_match, tblFeaturesLibrary.level <= (char.level or 1))
                .order_by(tblFeaturesLibrary.level, tblFeaturesLibrary.name).all())
    best = {}
    for f in features:
        key = (f.level, (f.name or '').lower(), (f.subclass_name or '').lower())
        if key not in best or len(f.description or '') > len(best[key].description or ''):
            best[key] = f
    features = sorted(best.values(), key=lambda f: (f.level, (f.name or '').lower()))
    row = (tblClassLevelsLibrary.query.filter(func.lower(tblClassLevelsLibrary.class_name) == cls.lower(),
                                              tblClassLevelsLibrary.level == (char.level or 1)).first())
    level_info = None
    if row:
        try:
            slots = {int(k): v for k, v in _json.loads(row.spell_slots_json or '{}').items() if v}
        except Exception:
            slots = {}
        try:
            specific = _json.loads(row.class_specific_json or '{}')
        except Exception:
            specific = {}
        counters = {label: specific[key] for key, label in _CLASS_RESOURCE_NAMES.items()
                    if isinstance(specific.get(key), int) and specific[key] > 0}
        level_info = {'prof_bonus': row.prof_bonus, 'slots': slots, 'cantrips_known': row.cantrips_known,
                      'spells_known': row.spells_known, 'counters': counters}
    return features, level_info


@router.post('/character/{character_id}/suggest-resources')
def suggest_resources(character_id: int, user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    _, level_info = _class_progression(char)
    if not level_info:
        raise ApiError(404, f'No synced class table for "{char.char_class}" level {char.level}. '
                            f'Run Sync All on the API Settings page first.')
    existing = {(r.resource_name or '').strip().lower() for r in char.resources}
    order = max([r.order_by or 0 for r in char.resources], default=0)
    added = []
    wanted = [(f'Spell Slots L{lvl}', n) for lvl, n in sorted(level_info['slots'].items())]
    wanted += sorted(level_info['counters'].items())
    for name, count in wanted:
        if name.lower() in existing:
            continue
        order += 1
        db.session.add(tblCharacterResources(character_id=character_id, resource_name=name,
                                             current_val=count, max_val=count, order_by=order))
        added.append(name)
    db.session.commit()
    relay_broadcaster.push_character(char)
    return {'ok': True, 'added': added,
            'message': (f'Added: {", ".join(added)}' if added else 'Nothing to add — all suggested resources already exist.')}


# ── character sheet page data ─────────────────────────────────────────────────

@api.get('/characters/{character_id}/page')
def character_sheet_page(character_id: int, user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    if not _can_edit(user, char):
        raise ApiError(403, 'You do not have access to that character.', code='forbidden')
    all_players = []
    if user.is_dm():
        from models.user import tblUsers
        all_players = [u.to_dict() for u in tblUsers.query.filter_by(active=1).order_by(tblUsers.display_name).all()]
    races_lib = {r.name.lower(): {'name': r.name, 'speed': r.speed, 'size': r.size, 'ability_bonuses': r.ability_bonuses,
                                  'traits_text': r.traits_text, 'languages': r.languages, 'description': r.description,
                                  'game_system': r.game_system} for r in tblRacesLibrary.query.all()}
    classes_lib = {c.name.lower(): {'name': c.name, 'hit_die': c.hit_die, 'saving_throws': c.saving_throws,
                                    'proficiencies': c.proficiencies, 'skill_choices': c.skill_choices, 'subclasses': c.subclasses,
                                    'spellcasting_ability': c.spellcasting_ability, 'description': c.description,
                                    'game_system': c.game_system} for c in tblClassesLibrary.query.all()}
    class_features, class_level_info = _class_progression(char)
    subclass_options = []
    if char.char_class:
        from sqlalchemy import func
        from models.ttrpg import tblSubclassesLibrary
        subclass_options = [s.name for s in tblSubclassesLibrary.query
                            .filter(func.lower(tblSubclassesLibrary.class_name) == char.char_class.strip().lower())
                            .order_by(tblSubclassesLibrary.name).all()]
    from models.ttrpg import tblWeaponPropertiesLibrary
    weapon_props = {w.name.lower(): w.description for w in tblWeaponPropertiesLibrary.query.all() if w.description}
    from ttrpg.genre_packs import genre_display, get_pack
    _pack = get_pack(getattr(char, 'genre', '') or '')
    genre_archetype, genre_species = genre_display(char.genre, char.char_class, char.race) if _pack else ('', '')
    ctx = _sheet_context(char)
    if ctx['game']['id'] != (char.game_system or 'dnd5e'):
        ctx['game'] = {'id': char.game_system or 'dnd5e', 'name': dice_systems.system(char.game_system)['name'], 'settings': {}}
    return {'char': char_full(char), **ctx, 'is_dcc': char.is_dcc, 'all_players': all_players, 'conditions': condition_texts(),
            'races_lib': races_lib, 'classes_lib': classes_lib,
            'class_features': [{'name': f.name, 'level': f.level, 'subclass_name': f.subclass_name or '',
                                'description': f.description or ''} for f in class_features],
            'class_level_info': class_level_info, 'subclass_options': subclass_options, 'weapon_props': weapon_props,
            'genre_archetype': genre_archetype, 'genre_species': genre_species,
            'genre_art': _pack['art_style'] if _pack else [], 'genre_label': _pack['label'] if _pack else '',
            'can_edit': _can_edit(user, char), 'is_dm': user.is_dm(), 'current_user_id': user.user_id}


@api.get('/characters/{character_id}/edit-options')
def character_edit_options(character_id: int, user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    if not _can_edit(user, char):
        raise ApiError(403, 'You do not have access to that character.', code='forbidden')
    return {'char': char_full(char), **_sheet_context(char)}


@api.post('/characters/{character_id}')
def character_edit(character_id: int, form: dict = Depends(form_or_json), portrait: UploadFile = File(None),
                   user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    if not _can_edit(user, char):
        raise ApiError(403, 'You do not have access to that character.', code='forbidden')
    name = (form.get('name') or '').strip()
    if not name:
        raise ApiError(400, 'Character name is required.')
    char.name = name
    char.char_class = (form.get('char_class') or '').strip()
    char.race = (form.get('race') or '').strip()
    char.level = _int(form, 'level', char.level) or char.level
    char.background = (form.get('background') or '').strip()
    char.hp_max = _int(form, 'hp_max', char.hp_max) or char.hp_max
    char.hp_current = _int(form, 'hp_current', char.hp_current) or char.hp_current
    char.hp_current = max(0, min(char.hp_max, char.hp_current))
    for f, cur in (('ac', char.ac), ('str_val', char.str_val), ('dex_val', char.dex_val), ('con_val', char.con_val),
                   ('int_val', char.int_val), ('wis_val', char.wis_val), ('cha_val', char.cha_val), ('speed', char.speed),
                   ('passive_perception', char.passive_perception)):
        setattr(char, f, _int(form, f, cur) or cur)
    char.initiative_bonus = _int(form, 'initiative_bonus', char.initiative_bonus)
    char.gold = _int(form, 'gold', char.gold)
    char.silver = _int(form, 'silver', char.silver)
    char.copper = _int(form, 'copper', char.copper)
    gs = form.get('game_system')
    if gs in dice_systems.SYSTEMS:
        char.game_system = gs
    if char.is_dcc:
        char.dcc_json = _json.dumps(_dcc_fields_from(form, char.dcc_json))
        char.hp_max = dice_systems.DCC_HB_SLOTS
        char.hp_current = max(0, min(char.hp_max, char.hp_current))
        _sync_mana(char)
    if portrait and portrait.filename and _allowed_file(portrait.filename):
        _drop_portrait(char)
        char.portrait_path = save_upload_downscaled(portrait, PORTRAIT_FOLDER)
    elif _portrait_ref(form):
        _drop_portrait(char)
        char.portrait_path = _portrait_ref(form)
    db.session.commit()
    return {'ok': True, 'character_id': char.character_id}


# ── inline field save ─────────────────────────────────────────────────────────

@router.post('/character/{character_id}/save-field')
def save_field(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    field = data.get('field')
    value = data.get('value')
    int_fields = {'hp_current', 'hp_max', 'ac', 'str_val', 'dex_val', 'con_val', 'int_val', 'wis_val', 'cha_val', 'speed',
                  'initiative_bonus', 'passive_perception', 'gold', 'silver', 'copper', 'level'}
    text_fields = {'name', 'char_class', 'subclass', 'race', 'background'}
    if field in int_fields:
        setattr(char, field, int(value or 0))
    elif field in text_fields:
        setattr(char, field, str(value or ''))
    elif field == 'game_system':
        char.game_system = value if value in dice_systems.SYSTEMS else dice_systems.DEFAULT_SYSTEM
        if char.is_dcc and char.hp_max != dice_systems.DCC_HB_SLOTS:
            char.hp_max = dice_systems.DCC_HB_SLOTS
            char.hp_current = dice_systems.DCC_HB_SLOTS
    elif field and field.startswith('dcc_'):
        char.dcc_json = _json.dumps(_dcc_fields_from({field: value}, char.dcc_json))
    else:
        raise ApiError(400, 'unknown field')
    if char.is_dcc:
        _sync_mana(char)
    db.session.commit()
    if field in ('hp_current', 'hp_max'):
        token_id = relay_broadcaster.find_token_id('player', char.character_id)
        if token_id:
            relay_broadcaster.broadcast_token_health(token_id, char.hp_current, char.hp_max)
    relay_broadcaster.push_character(char)
    return {'ok': True, 'hp_pct': char.hp_pct()}


def _sync_mana(char):
    for r in char.resources:
        if r.resource_name.strip().lower() == 'mana':
            if r.max_val != char.mana_max():
                r.max_val = char.mana_max()
                r.current_val = min(r.current_val, r.max_val)
            return


@router.post('/character/{character_id}/apply-library')
def apply_library(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    from models.ttrpg import apply_library_bonuses
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    kind = data.get('kind', 'race')
    if kind not in ('race', 'class'):
        raise ApiError(400, 'kind must be race or class')
    out = apply_library_bonuses(char, kind, db)
    if out['ok']:
        _sync_mana(char)
        db.session.commit()
        relay_broadcaster.push_character(char)
    return out


@router.post('/character/{character_id}/hp-delta')
def hp_delta(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    slots = None
    if char.is_dcc and data.get('damage') is not None:
        slots = dice_systems.dcc_damage_slots(data.get('damage'), char.dr_total(), char.hb_slot_value())
        delta = -slots
    else:
        delta = int(data.get('delta', 0))
    char.hp_current = max(0, min(char.hp_max, char.hp_current + delta))
    db.session.commit()
    token_id = relay_broadcaster.find_token_id('player', char.character_id)
    if token_id:
        relay_broadcaster.broadcast_token_health(token_id, char.hp_current, char.hp_max)
    relay_broadcaster.push_character(char)
    return {'ok': True, 'hp_current': char.hp_current, 'hp_pct': char.hp_pct(), 'slots_lost': slots}


@router.post('/character/{character_id}/condition')
def character_condition(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    action = data.get('action')
    condition = (data.get('condition') or '').strip()
    if action == 'add' and condition:
        if not any(c.condition_name == condition for c in char.conditions):
            db.session.add(tblCharacterConditions(character_id=character_id, condition_name=condition, created_at=_now()))
            db.session.commit()
    elif action == 'remove' and condition:
        cond = tblCharacterConditions.query.filter_by(character_id=character_id, condition_name=condition).first()
        if cond:
            db.session.delete(cond)
            db.session.commit()
    conds = [c.condition_name for c in char.conditions]
    relay_broadcaster.broadcast_condition_update(conds, player_name=char.name)
    return {'ok': True, 'conditions': conds}


@router.post('/resource/{resource_id}/delta')
def resource_delta(resource_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    r = tblCharacterResources.query.get_or_404(resource_id)
    _own_or_403(user, r.character)
    delta = int(data.get('delta', 0))
    r.current_val = max(0, min(r.max_val, r.current_val + delta))
    db.session.commit()
    return {'ok': True, 'current_val': r.current_val, 'max_val': r.max_val}


@router.post('/character/{character_id}/assign')
def character_assign(character_id: int, form: dict = Depends(form_or_json), user=Depends(require_dm)):
    char = tblCharacters.query.get_or_404(character_id)
    try:
        new_user_id = int(form.get('user_id') or 0)
    except (TypeError, ValueError):
        new_user_id = 0
    msg = ''
    if new_user_id:
        from models.user import tblUsers
        u = db.session.get(tblUsers, new_user_id)
        if u:
            char.user_id = new_user_id
            db.session.commit()
            relay_broadcaster.push_character(char)
            msg = f'{char.name} reassigned to {u.display_name}.'
    return {'ok': True, 'message': msg}


@router.post('/character/{character_id}/portrait')
def upload_portrait(character_id: int, form: dict = Depends(form_or_json), portrait: UploadFile = File(None),
                    user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    if not (portrait and portrait.filename) and _portrait_ref(form):
        _drop_portrait(char)
        char.portrait_path = _portrait_ref(form)
        db.session.commit()
    elif portrait and portrait.filename and _allowed_file(portrait.filename):
        _drop_portrait(char)
        char.portrait_path = save_upload_downscaled(portrait, PORTRAIT_FOLDER)
        db.session.commit()
    return {'ok': True, 'url': portrait_url(char)}


@router.post('/character/{character_id}/portrait-paste')
def portrait_paste(character_id: int, portrait: UploadFile = File(None), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    if not portrait:
        raise ApiError(400, 'no file')
    _drop_portrait(char)
    char.portrait_path = save_upload_downscaled(portrait, PORTRAIT_FOLDER)
    db.session.commit()
    return {'ok': True, 'url': '/static/uploads/portraits/' + char.portrait_path}


@router.post('/character/{character_id}/delete')
def character_delete(character_id: int, user=Depends(require_dm)):
    char = tblCharacters.query.get_or_404(character_id)
    char.active = 0
    db.session.commit()
    return {'ok': True, 'message': f'Character "{char.name}" removed.'}


# ── sub-item CRUD ─────────────────────────────────────────────────────────────

def _sub_delete_or_update(request, entry, user):
    _own_or_403(user, entry.character)
    if request.method == 'DELETE':
        db.session.delete(entry)
        db.session.commit()
        return True
    return False


@router.post('/character/{character_id}/resources')
def resource_add(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    r = tblCharacterResources(character_id=character_id, resource_name=(data.get('resource_name') or '').strip(),
                              current_val=int(data.get('current_val', 0) or 0), max_val=int(data.get('max_val', 0) or 0),
                              order_by=len(char.resources))
    db.session.add(r)
    db.session.commit()
    return {'ok': True, 'resource_id': r.resource_id}


@router.api_route('/resource/{resource_id}', methods=['POST', 'DELETE'])
def resource_update(resource_id: int, request: Request, data: dict = Depends(json_body), user=Depends(require_user)):
    r = tblCharacterResources.query.get_or_404(resource_id)
    if _sub_delete_or_update(request, r, user):
        return {'ok': True}
    r.resource_name = data.get('resource_name', r.resource_name)
    r.current_val = int(data.get('current_val', r.current_val) or 0)
    r.max_val = int(data.get('max_val', r.max_val) or 0)
    db.session.commit()
    return {'ok': True}


@router.post('/character/{character_id}/skills')
def skill_add(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    s = tblCharacterSkills(character_id=character_id, skill_name=(data.get('skill_name') or '').strip(),
                           bonus=int(data.get('bonus', 0) or 0), proficient=int(data.get('proficient', 0) or 0),
                           category=(data.get('category') or '')[:20], stat=(data.get('stat') or '')[:5],
                           order_by=len(char.skills))
    db.session.add(s)
    db.session.commit()
    return {'ok': True, 'skill_id': s.skill_id}


@router.api_route('/skill/{skill_id}', methods=['POST', 'DELETE'])
def skill_update(skill_id: int, request: Request, data: dict = Depends(json_body), user=Depends(require_user)):
    s = tblCharacterSkills.query.get_or_404(skill_id)
    if _sub_delete_or_update(request, s, user):
        return {'ok': True}
    s.skill_name = data.get('skill_name', s.skill_name)
    s.bonus = int(data.get('bonus', s.bonus) or 0)
    s.proficient = int(data.get('proficient', s.proficient) or 0)
    if 'category' in data:
        s.category = (data.get('category') or '')[:20]
    if 'stat' in data:
        s.stat = (data.get('stat') or '')[:5]
    db.session.commit()
    return {'ok': True}


@router.post('/character/{character_id}/inventory')
def inventory_add(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    item = tblCharacterInventory(character_id=character_id, item_name=(data.get('item_name') or '').strip(),
                                 quantity=int(data.get('quantity', 1) or 1), weight=data.get('weight', ''),
                                 notes=data.get('notes', ''), equipped=int(data.get('equipped', 0) or 0),
                                 hotlist=int(data.get('hotlist', 0) or 0), order_by=len(char.inventory))
    db.session.add(item)
    db.session.commit()
    return {'ok': True, 'item_id': item.item_id}


@router.api_route('/inventory/{item_id}', methods=['POST', 'DELETE'])
def inventory_update(item_id: int, request: Request, data: dict = Depends(json_body), user=Depends(require_user)):
    item = tblCharacterInventory.query.get_or_404(item_id)
    if _sub_delete_or_update(request, item, user):
        return {'ok': True}
    item.item_name = data.get('item_name', item.item_name)
    item.quantity = int(data.get('quantity', item.quantity) or 1)
    item.weight = data.get('weight', item.weight)
    item.notes = data.get('notes', item.notes)
    item.equipped = int(data.get('equipped', item.equipped) or 0)
    if 'hotlist' in data:
        item.hotlist = int(data.get('hotlist') or 0)
    db.session.commit()
    return {'ok': True}


@router.post('/character/{character_id}/notes')
def note_add(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    note = tblCharacterNotes(character_id=character_id, note_text=(data.get('note_text') or '').strip(), created_at=_now())
    db.session.add(note)
    db.session.commit()
    return {'ok': True, 'note_id': note.note_id, 'created_at': note.created_at}


@router.api_route('/note/{note_id}', methods=['POST', 'DELETE'])
def note_update(note_id: int, request: Request, data: dict = Depends(json_body), user=Depends(require_user)):
    note = tblCharacterNotes.query.get_or_404(note_id)
    if _sub_delete_or_update(request, note, user):
        return {'ok': True}
    note.note_text = (data.get('note_text', note.note_text) or '').strip()
    db.session.commit()
    return {'ok': True}


@router.post('/character/{character_id}/feats')
def feat_add(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    feat_name = (data.get('feat_name') or '').strip()
    if not feat_name:
        raise ApiError(400, 'Feat name is required')
    feat = tblCharacterFeats(character_id=character_id, feat_name=feat_name,
                             description=(data.get('description') or '').strip(), order_by=len(char.feats))
    db.session.add(feat)
    db.session.commit()
    return {'ok': True, 'feat_id': feat.feat_id}


@router.api_route('/feat/{feat_id}', methods=['POST', 'DELETE'])
def feat_update(feat_id: int, request: Request, data: dict = Depends(json_body), user=Depends(require_user)):
    feat = tblCharacterFeats.query.get_or_404(feat_id)
    if _sub_delete_or_update(request, feat, user):
        return {'ok': True}
    feat.feat_name = (data.get('feat_name', feat.feat_name) or '').strip() or feat.feat_name
    feat.description = data.get('description', feat.description)
    db.session.commit()
    return {'ok': True}


@router.post('/character/{character_id}/armor')
def armor_add_to_char(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    entry = tblCharacterArmor(
        character_id=character_id, armor_lib_id=data.get('armor_lib_id') or None,
        armor_name=(data.get('armor_name') or '').strip(), armor_category=data.get('armor_category', ''),
        armor_class_base=int(data.get('armor_class_base', 0) or 0), dex_bonus=int(data.get('dex_bonus', 0) or 0),
        max_dex_bonus=data.get('max_dex_bonus'), ac_bonus=int(data.get('ac_bonus', 0) or 0),
        equipped=int(data.get('equipped', 0) or 0), notes=(data.get('notes') or '').strip(), order_by=len(char.armor))
    db.session.add(entry)
    db.session.commit()
    return {'ok': True, 'char_armor_id': entry.char_armor_id}


@router.api_route('/char-armor/{char_armor_id}', methods=['POST', 'DELETE'])
def armor_update(char_armor_id: int, request: Request, data: dict = Depends(json_body), user=Depends(require_user)):
    entry = tblCharacterArmor.query.get_or_404(char_armor_id)
    if _sub_delete_or_update(request, entry, user):
        return {'ok': True}
    if 'equipped' in data:
        entry.equipped = int(data['equipped'])
    if 'ac_bonus' in data:
        entry.ac_bonus = int(data.get('ac_bonus') or 0)
    if 'notes' in data:
        entry.notes = (data['notes'] or '').strip()
    db.session.commit()
    return {'ok': True}


@router.post('/character/{character_id}/weapons')
def weapon_add_to_char(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    entry = tblCharacterWeapons(
        character_id=character_id, weapon_lib_id=data.get('weapon_lib_id') or None,
        weapon_name=(data.get('weapon_name') or '').strip(), weapon_category=data.get('weapon_category', ''),
        weapon_range=data.get('weapon_range', ''), damage_dice=data.get('damage_dice', ''),
        damage_type=data.get('damage_type', ''), two_handed_damage_dice=data.get('two_handed_damage_dice', ''),
        two_handed_damage_type=data.get('two_handed_damage_type', ''), range_normal=int(data.get('range_normal', 0) or 0),
        range_long=int(data.get('range_long', 0) or 0), attack_bonus=int(data.get('attack_bonus', 0) or 0),
        damage_bonus=int(data.get('damage_bonus', 0) or 0), properties=data.get('properties', ''),
        equipped=int(data.get('equipped', 0) or 0), notes=(data.get('notes') or '').strip(), order_by=len(char.weapons))
    db.session.add(entry)
    db.session.commit()
    return {'ok': True, 'char_weapon_id': entry.char_weapon_id}


@router.api_route('/char-weapon/{char_weapon_id}', methods=['POST', 'DELETE'])
def weapon_char_update(char_weapon_id: int, request: Request, data: dict = Depends(json_body), user=Depends(require_user)):
    entry = tblCharacterWeapons.query.get_or_404(char_weapon_id)
    if _sub_delete_or_update(request, entry, user):
        return {'ok': True}
    if 'equipped' in data:
        entry.equipped = int(data['equipped'])
    if 'attack_bonus' in data:
        entry.attack_bonus = int(data.get('attack_bonus') or 0)
    if 'damage_bonus' in data:
        entry.damage_bonus = int(data.get('damage_bonus') or 0)
    if 'notes' in data:
        entry.notes = (data['notes'] or '').strip()
    db.session.commit()
    return {'ok': True}


@router.post('/character/{character_id}/spells')
def spell_add_to_char(character_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    char = tblCharacters.query.get_or_404(character_id)
    _own_or_403(user, char)
    spell_name = (data.get('spell_name') or '').strip()
    if not spell_name:
        raise ApiError(400, 'Spell name is required')
    entry = tblCharacterSpells(character_id=character_id, spell_lib_id=data.get('spell_lib_id') or None,
                               spell_name=spell_name, spell_level=int(data.get('spell_level', 0) or 0),
                               school=(data.get('school') or '').strip(), prepared=int(data.get('prepared', 0) or 0),
                               notes=(data.get('notes') or '').strip(), order_by=len(char.spells))
    db.session.add(entry)
    db.session.commit()
    return {'ok': True, 'char_spell_id': entry.char_spell_id}


@router.api_route('/char-spell/{char_spell_id}', methods=['POST', 'DELETE'])
def spell_char_update(char_spell_id: int, request: Request, data: dict = Depends(json_body), user=Depends(require_user)):
    entry = tblCharacterSpells.query.get_or_404(char_spell_id)
    if _sub_delete_or_update(request, entry, user):
        return {'ok': True}
    if 'prepared' in data:
        entry.prepared = int(data['prepared'])
    if 'notes' in data:
        entry.notes = (data['notes'] or '').strip()
    db.session.commit()
    return {'ok': True}


# ── dice ──────────────────────────────────────────────────────────────────────

def roll_dict(r):
    return {'roll_id': r.roll_id, 'char_name': r.char_name, 'expression': r.expression, 'label': r.label,
            'dice': _json.loads(r.dice_json or '[]'), 'modifier': r.modifier, 'total': r.total,
            'adv_mode': r.adv_mode, 'rolled_at': r.rolled_at}


@router.post('/dice/roll')
def dice_roll(data: dict = Depends(json_body), user=Depends(require_user)):
    char_id = data.get('character_id')
    char_name = (data.get('char_name') or 'Unknown')[:60]
    count = max(1, min(20, int(data.get('count', 1) or 1)))
    sides = int(data.get('sides', 20))
    modifier = max(-99, min(99, int(data.get('modifier', 0) or 0)))
    label = (data.get('label') or '').strip()[:80]
    adv_mode = data.get('adv_mode', 'normal')
    game = active_game_info()
    if char_id:
        _ch = db.session.get(tblCharacters, int(char_id)) if str(char_id).isdigit() else None
        if _ch is not None and (_ch.game_system or 'dnd5e') != game['id']:
            game = {'id': _ch.game_system or 'dnd5e', 'name': dice_systems.system(_ch.game_system)['name'], 'settings': {}}
    roll_type = (data.get('roll_type') or 'other')[:20]
    difficulty = data.get('difficulty')
    rank = data.get('rank')
    try:
        floor = int(data.get('floor', game['settings'].get('floor', 0)) or 0)
    except (TypeError, ValueError):
        floor = int(game['settings'].get('floor', 0) or 0)
    if sides not in (2, 4, 6, 8, 10, 12, 20, 100):
        sides = 20
    if adv_mode in ('advantage', 'disadvantage'):
        num = max(2, count)
        dice = [random.randint(1, sides) for _ in range(num)]
        kept = max(dice) if adv_mode == 'advantage' else min(dice)
        total = kept + modifier
    else:
        adv_mode = 'normal'
        num = count
        dice = [random.randint(1, sides) for _ in range(count)]
        total = sum(dice) + modifier
    expr = f'{num}d{sides}'
    if modifier > 0:
        expr += f'+{modifier}'
    elif modifier < 0:
        expr += str(modifier)
    natural = kept if adv_mode != 'normal' else (dice[0] if len(dice) == 1 else None)
    outcome = dice_systems.evaluate(game['id'], sides, natural, total, roll_type, difficulty, floor, rank)
    label = dice_systems.annotate_label(label, outcome, difficulty)[:120]
    roll = tblDiceRolls(character_id=char_id, char_name=char_name, expression=expr, label=label,
                        dice_json=_json.dumps(dice), modifier=modifier, total=total, adv_mode=adv_mode, rolled_at=_now())
    db.session.add(roll)
    db.session.flush()
    old = db.session.query(tblDiceRolls.roll_id).order_by(tblDiceRolls.roll_id.desc()).offset(50).all()
    if old:
        tblDiceRolls.query.filter(tblDiceRolls.roll_id.in_([r[0] for r in old])).delete(synchronize_session=False)
    db.session.commit()
    try:
        relay_broadcaster.broadcast_roll(char_name, expr, label, dice, modifier, total, adv_mode)
    except Exception:
        pass
    out = {'ok': True, 'roll_id': roll.roll_id, 'char_name': char_name, 'expression': expr, 'label': label,
           'dice': dice, 'modifier': modifier, 'total': total, 'adv_mode': adv_mode, 'rolled_at': roll.rolled_at,
           'outcome': outcome, 'difficulty': difficulty, 'system': game['id']}
    events.emit('dice', {'kind': 'roll', 'roll': roll_dict(roll)})
    return out


@router.get('/dice/system')
def dice_system(user=Depends(require_user)):
    return active_game_info()


def clear_roll_history():
    from datetime import timezone
    from models.tblRollLog import tblRollLog
    from sql import appsettingSet
    appsettingSet('relay_roll_cleared_at', datetime.now(timezone.utc).isoformat())
    removed = tblDiceRolls.query.delete()
    removed += tblRollLog.query.delete()
    db.session.commit()
    return removed


@router.post('/dice/clear')
def dice_clear(user=Depends(require_dm)):
    n = clear_roll_history()
    events.emit('dice', {'kind': 'clear'})
    return {'ok': True, 'removed': n}


@router.get('/dice/feed')
def dice_feed(since: int = 0, user=Depends(require_user)):
    q = tblDiceRolls.query
    if since:
        q = q.filter(tblDiceRolls.roll_id > since)
    rolls = (q.order_by(tblDiceRolls.rolled_at.desc(), tblDiceRolls.relay_roll_id.is_(None),
                        tblDiceRolls.relay_roll_id.desc(), tblDiceRolls.roll_id.desc()).limit(50).all())
    return [roll_dict(r) for r in rolls]


# ── sessions ──────────────────────────────────────────────────────────────────

@api.get('/sessions')
def sessions_list(user=Depends(require_dm)):
    sessions = tblSessions.query.order_by(tblSessions.created_at.desc()).all()
    return {'sessions': [session_brief(s) for s in sessions]}


@api.get('/sessions/new-options')
def session_new_options(user=Depends(require_dm)):
    campaigns = tblcampaigns.query.order_by(tblcampaigns.campaign_name).all()
    characters = tblCharacters.query.filter_by(active=1).order_by(tblCharacters.name).all()
    return {'campaigns': [{'campaign_id': c.campaign_id, 'campaign_name': c.campaign_name} for c in campaigns],
            'game_systems': _systems(), 'characters': [char_brief(c) for c in characters],
            'today': datetime.now().strftime('%Y-%m-%d')}


@api.post('/sessions')
def session_create(form: dict = Depends(form_or_json), user=Depends(require_dm)):
    title = (form.get('title') or '').strip()
    if not title:
        raise ApiError(400, 'Session title is required.')
    campaign_id = form.get('campaign_id') or None
    if campaign_id:
        campaign_id = int(campaign_id)
    game_system, system_settings = _game_fields_from(form)
    sess = tblSessions(title=title, session_number=_int(form, 'session_number', 1) or 1, campaign_id=campaign_id,
                       status='planning', session_date=form.get('session_date', '') or '', created_at=_now(),
                       game_system=game_system, system_settings=system_settings)
    db.session.add(sess)
    db.session.flush()
    ids = form.get('character_ids') or []
    if isinstance(ids, (str, int)):
        ids = [ids]
    for cid in ids:
        db.session.add(tblSessionParty(session_id=sess.session_id, character_id=int(cid), is_active=1, joined_at=_now()))
    db.session.commit()
    return {'ok': True, 'session_id': sess.session_id}


@api.get('/sessions/{session_id}/page')
def session_page(session_id: int, user=Depends(require_dm)):
    sess = tblSessions.query.get_or_404(session_id)
    campaigns = tblcampaigns.query.order_by(tblcampaigns.campaign_name).all()
    all_chars = tblCharacters.query.filter_by(active=1).order_by(tblCharacters.name).all()
    party_ids = [sp.character_id for sp in sess.party]
    campaign_scenes = []
    if sess.campaign_id:
        campaign_scenes = tblscenes.query.filter_by(campaign_id=sess.campaign_id, active=1).order_by(tblscenes.orderBy).all()
    try:
        from extensions import currentvolume
        current_vol = currentvolume()
    except Exception:
        current_vol = 50
    obs_scene_links, obs_links_live = {}, False
    try:
        from routers.obs import scene_link_map, scene_links_live
        obs_scene_links = scene_link_map()
        obs_links_live = scene_links_live()
    except Exception:
        pass
    active_map = next((m for m in sess.battle_maps if m.is_active == 1), None)
    monsters = []
    for sm in sess.monsters:
        try:
            mstats = _json.loads(sm.template.stats_json or '{}') if sm.template else {}
        except ValueError:
            mstats = {}
        img = mstats.get('image') or ''
        if img and not (img.startswith('http') or img.startswith('/static/') or img.startswith('data:')):
            img = 'https://www.dnd5eapi.co' + img
        try:
            conds = _json.loads(sm.conditions or '[]')
        except ValueError:
            conds = []
        monsters.append({'monster_id': sm.monster_id, 'display_name': sm.display_name, 'hp_current': sm.hp_current,
                         'hp_max': sm.hp_max, 'hp_pct': sm.hp_pct(), 'hp_color': _hp_color(sm.hp_pct()), 'ac': sm.ac,
                         'initiative': sm.initiative, 'conditions': conds, 'is_alive': sm.is_alive,
                         'sort_order': sm.sort_order, 'image': img, 'size': mstats.get('size') or '',
                         'type': mstats.get('type') or ''})
    return {
        'sess': session_brief(sess),
        'campaigns': [{'campaign_id': c.campaign_id, 'campaign_name': c.campaign_name} for c in campaigns],
        'game_systems': _systems(), 'game': sess.game_info(),
        'all_chars': [char_brief(c) for c in all_chars], 'party_ids': party_ids,
        'party': [char_brief(sp.character) for sp in sess.party if sp.character],
        'conditions': condition_texts(),
        'campaign_scenes': [{'scene_ID': s.scene_ID, 'sceneName': s.sceneName,
                             'obs_scene': (obs_scene_links or {}).get(s.scene_ID)} for s in campaign_scenes],
        'obs_links_live': obs_links_live, 'current_vol': current_vol,
        'active_map': {'map_id': active_map.map_id, 'name': active_map.name} if active_map else None,
        'monsters': monsters,
    }


@router.post('/sessions/{session_id}/status')
def session_status(session_id: int, form: dict = Depends(form_or_json), user=Depends(require_dm)):
    sess = tblSessions.query.get_or_404(session_id)
    new_status = form.get('status')
    if new_status in ('planning', 'active', 'ended'):
        if new_status == 'active':
            tblSessions.query.filter_by(status='active').update({'status': 'ended'})
        sess.status = new_status
        db.session.commit()
        if new_status == 'active':
            relay_broadcaster.push_all_characters()
            relay_broadcaster.push_session_users()
            relay_broadcaster.push_character_feeds()
        events.emit(f'session:{session_id}', {'status': sess.status})
        events.emit('dice', {'kind': 'system', 'game': active_game_info()})
    return {'ok': True, 'status': sess.status}


@router.get('/sessions/{session_id}/notes/list')
def session_notes_list(session_id: int, user=Depends(require_dm)):
    tblSessions.query.get_or_404(session_id)
    notes = (tblSessionNotes.query.filter_by(session_id=session_id)
             .order_by(tblSessionNotes.sort_order, tblSessionNotes.note_id.desc()).all())
    return {'ok': True, 'notes': [{'note_id': n.note_id, 'title': n.title, 'body': n.body, 'updated_at': n.updated_at}
                                  for n in notes]}


@router.post('/sessions/{session_id}/notes/add')
def session_notes_add(session_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    tblSessions.query.get_or_404(session_id)
    min_sort = db.session.query(db.func.min(tblSessionNotes.sort_order)).filter_by(session_id=session_id).scalar()
    n = tblSessionNotes(session_id=session_id, title=(data.get('title') or '').strip()[:120], body=data.get('body') or '',
                        sort_order=(min_sort - 1) if min_sort is not None else 0, created_at=_now(), updated_at=_now())
    db.session.add(n)
    db.session.commit()
    return {'ok': True, 'note_id': n.note_id}


@router.post('/sessions/{session_id}/notes/{note_id}/update')
def session_notes_update(session_id: int, note_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    n = tblSessionNotes.query.get_or_404(note_id)
    if n.session_id != session_id:
        raise ApiError(403, 'forbidden')
    if 'title' in data:
        n.title = (data.get('title') or '').strip()[:120]
    if 'body' in data:
        n.body = data.get('body') or ''
    n.updated_at = _now()
    db.session.commit()
    return {'ok': True}


@router.post('/sessions/{session_id}/notes/{note_id}/reorder')
def session_notes_reorder(session_id: int, note_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    n = tblSessionNotes.query.get_or_404(note_id)
    if n.session_id != session_id:
        raise ApiError(403, 'forbidden')
    direction = data.get('direction', '')
    notes = (tblSessionNotes.query.filter_by(session_id=session_id)
             .order_by(tblSessionNotes.sort_order, tblSessionNotes.note_id.desc()).all())
    for i, x in enumerate(notes):
        x.sort_order = i
    idx = next((i for i, x in enumerate(notes) if x.note_id == note_id), None)
    if idx is not None:
        swap = idx - 1 if direction == 'up' else idx + 1 if direction == 'down' else None
        if swap is not None and 0 <= swap < len(notes):
            notes[idx].sort_order, notes[swap].sort_order = notes[swap].sort_order, notes[idx].sort_order
    db.session.commit()
    return {'ok': True}


@router.post('/sessions/{session_id}/notes/{note_id}/delete')
def session_notes_delete(session_id: int, note_id: int, user=Depends(require_dm)):
    n = tblSessionNotes.query.get_or_404(note_id)
    if n.session_id != session_id:
        raise ApiError(403, 'forbidden')
    db.session.delete(n)
    db.session.commit()
    return {'ok': True}


@router.get('/sessions/{session_id}/mapnotes/list')
def session_mapnotes_list(session_id: int, user=Depends(require_dm)):
    from models.ttrpg import tblBattleMapNotes, tblBattleMaps
    tblSessions.query.get_or_404(session_id)
    maps = tblBattleMaps.query.filter_by(session_id=session_id).order_by(tblBattleMaps.sort_order, tblBattleMaps.map_id).all()
    out = []
    for m in maps:
        notes = (tblBattleMapNotes.query.filter_by(map_id=m.map_id)
                 .order_by(tblBattleMapNotes.sort_order, tblBattleMapNotes.note_id.desc()).all())
        out.append({'map_id': m.map_id, 'name': m.name,
                    'notes': [{'note_id': n.note_id, 'title': n.title, 'body': n.body, 'updated_at': n.updated_at} for n in notes]})
    return {'ok': True, 'maps': out}


@router.post('/sessions/{session_id}/edit')
def session_edit(session_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    sess = tblSessions.query.get_or_404(session_id)
    if 'title' in data:
        title = (data['title'] or '').strip()
        if title:
            sess.title = title
    if 'session_number' in data:
        try:
            sess.session_number = int(data['session_number'])
        except (ValueError, TypeError):
            pass
    if 'session_date' in data:
        sess.session_date = data['session_date'] or ''
    if 'campaign_id' in data:
        cid = data['campaign_id']
        sess.campaign_id = int(cid) if cid else None
    GAME_KEYS = ('game_system', 'floor', 'collapse_at', 'collapse_note')
    if any(k in data for k in GAME_KEYS):
        cur = sess.game_info()['settings']
        src = {'game_system': data.get('game_system') or sess.game_system}
        for k in GAME_KEYS[1:]:
            src[k] = data.get(k, cur.get(k))
        sess.game_system, sess.system_settings = _game_fields_from(src)
    db.session.commit()
    if sess.status == 'active':
        relay_broadcaster.broadcast_game(sess)
        events.emit('dice', {'kind': 'system', 'game': active_game_info()})
    events.emit(f'session:{session_id}', {'edited': True})
    campaign_name = sess.campaign.campaign_name if sess.campaign else None
    return {'ok': True, 'campaign_name': campaign_name, 'title': sess.title, 'session_number': sess.session_number,
            'session_date': sess.session_date, 'game': sess.game_info()}


@router.post('/sessions/{session_id}/party/add')
def session_party_add(session_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    char_id = int(data.get('character_id'))
    existing = tblSessionParty.query.filter_by(session_id=session_id, character_id=char_id).first()
    if not existing:
        db.session.add(tblSessionParty(session_id=session_id, character_id=char_id, is_active=1, joined_at=_now()))
        db.session.commit()
    relay_broadcaster.push_all_characters()
    events.emit(f'session:{session_id}', {'party': True})
    return {'ok': True}


@router.post('/sessions/{session_id}/party/{char_id}/remove')
def session_party_remove(session_id: int, char_id: int, user=Depends(require_dm)):
    sp = tblSessionParty.query.filter_by(session_id=session_id, character_id=char_id).first_or_404()
    char_name = sp.character.name if sp.character else None
    db.session.delete(sp)
    db.session.commit()
    relay_broadcaster.push_all_characters()
    if char_name:
        relay_broadcaster.remove_character(char_name)
    events.emit(f'session:{session_id}', {'party': True})
    return {'ok': True}


@router.post('/sessions/{session_id}/delete')
def session_delete(session_id: int, user=Depends(require_dm)):
    from models.ttrpg import tblBattleMapTokens as _tblBattleMapTokens
    from models.ttrpg import tblBattleMaps as _tblBattleMaps
    sess = tblSessions.query.get_or_404(session_id)
    title = sess.title
    tblSessionParty.query.filter_by(session_id=session_id).delete()
    _tblSessionMonsters.query.filter_by(session_id=session_id).delete()
    map_ids = [m.map_id for m in _tblBattleMaps.query.filter_by(session_id=session_id).all()]
    if map_ids:
        _tblBattleMapTokens.query.filter(_tblBattleMapTokens.map_id.in_(map_ids)).delete(synchronize_session=False)
    _tblBattleMaps.query.filter_by(session_id=session_id).delete()
    db.session.delete(sess)
    db.session.commit()
    return {'ok': True, 'message': f'Session "{title}" deleted.'}


# the two routers are exposed as `router` (verbatim /ttrpg paths) and `open_router` slot reused for /api/v1
open_router = api
