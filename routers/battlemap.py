"""Battle maps (ported from routes/battlemap.py): map manager, the shared
map view's page data, the 2 s state poll (now also nudged by the
battlemap:<id> SSE topic), token / effect CRUD, floorplans, doors, prompts
and DM map notes. JSON paths under /ttrpg/battlemap keep their Flask shape;
the old form+redirect endpoints answer {ok, message} instead."""
import json
import os
import shutil
import uuid
import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

import core.config as config
import core.events as events
import ttrpg.floorplan as floorplan_mod
import integrations.relay_broadcaster as relay_broadcaster
from core.db import db
from extensions import currentvolume
from models.scenes import tblscenes
from models.ttrpg import (tblBattleMapDoors, tblBattleMapEffects, tblBattleMapFloorplans,
                          tblBattleMapNotes, tblBattleMapPrompts, tblBattleMaps, tblBattleMapTokens,
                          tblCharacters, tblSessionMonsters, tblSessionParty, tblSessions)
from routers._util import _now, form_or_json, json_body, save_upload_downscaled
from security.deps import ApiError, require_dm, require_user
from sql import appsettingGet
from core.urls import static_url

router = APIRouter(prefix='/ttrpg/battlemap')
api = APIRouter(prefix='/api/v1/battlemap')

UPLOAD_FOLDER = os.path.join(config.UPLOADS_DIR, 'battlemaps')
ALLOWED_EXT   = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'webm', 'ogv'}
VIDEO_EXT     = {'mp4', 'webm', 'ogv'}
CELL_PX       = 64

# D&D creature size → number of grid squares the token spans (square footprint).
# Players and unknown sizes default to 1×1.
_SIZE_SQUARES = {'tiny': 1, 'small': 1, 'medium': 1, 'large': 2, 'huge': 3, 'gargantuan': 4}


def _size_squares(size_str):
    return _SIZE_SQUARES.get((size_str or '').strip().lower(), 1)


def _bad(msg, status=400):
    return JSONResponse({'ok': False, 'error': msg}, status_code=status)


def _emit(map_id, kind):
    events.emit(f'battlemap:{map_id}', {'map_id': map_id, 'kind': kind})


def _bg_url(bm, external=False):
    return static_url(f'uploads/battlemaps/{bm.bg_image}', external=external) if bm.bg_image else ''


def _monster_img_url(image):
    """Resolve a monster image for a LOCAL page. SRD images are stored as dnd5eapi
    paths ('/api/...'); homebrew uploads as local '/static/...' paths."""
    if not image:
        return ''
    if image.startswith('http') or image.startswith('/static/') or image.startswith('data:'):
        return image
    return 'https://www.dnd5eapi.co' + image


def _monster_relay_img(image):
    """Resolve a monster image for the REMOTE relay portal, which can't reach this
    LAN server. SRD -> public dnd5eapi URL; homebrew local upload -> embedded as a
    data: URL so the portal renders it directly (mirrors map-background embedding)."""
    if not image:
        return ''
    if image.startswith('http') or image.startswith('data:'):
        return image
    if image.startswith('/static/'):
        fname = os.path.basename(image)
        path = os.path.join(config.UPLOADS_DIR, 'monsters', fname)
        try:
            with open(path, 'rb') as f:
                raw = f.read()
            ext = fname.rsplit('.', 1)[-1].lower()
            data, new_ext = relay_broadcaster._downscale_image(raw, ext, max_dim=512, quality=82)
            mime = 'jpeg' if new_ext == 'jpg' else new_ext
            return f'data:image/{mime};base64,{base64.b64encode(data).decode("ascii")}'
        except Exception:
            return ''
    return 'https://www.dnd5eapi.co' + image


def _monster_stats(sm):
    """Parse a session-monster's template stats_json ONCE (speed/type/ac/image)."""
    try:
        raw = json.loads(sm.template.stats_json or '{}') if sm.template else {}
    except (ValueError, TypeError):
        raw = {}
    raw_spd = raw.get('speed', {})
    walk = raw_spd.get('walk', 0) if isinstance(raw_spd, dict) else (raw_spd or 0)
    if isinstance(walk, str):
        walk = walk.replace(' ft.', '').replace(' ft', '').strip()
        try:
            walk = int(walk)
        except ValueError:
            walk = walk or 0    # keep the descriptive string; '' -> 0 (hidden)
    ac = raw.get('armor_class', 0)
    if isinstance(ac, list):
        ac = ac[0].get('value', 0) if ac and isinstance(ac[0], dict) else 0
    if not isinstance(ac, int):
        ac = 0
    if not ac and sm.template:
        ac = sm.template.ac or 0
    return {'speed': walk, 'type': raw.get('type', ''), 'ac': ac, 'image': raw.get('image') or ''}


def _fetch_token_entities(tokens):
    """Batch-load the entities behind a token list in two IN queries."""
    from sqlalchemy.orm import joinedload, selectinload
    monster_ids = [t.entity_id for t in tokens if t.entity_type == 'monster']
    char_ids    = [t.entity_id for t in tokens if t.entity_type == 'player']
    monsters, chars = {}, {}
    if monster_ids:
        rows = (tblSessionMonsters.query
                .options(joinedload(tblSessionMonsters.template))
                .filter(tblSessionMonsters.monster_id.in_(monster_ids)).all())
        monsters = {m.monster_id: m for m in rows}
    if char_ids:
        rows = (tblCharacters.query
                .options(selectinload(tblCharacters.conditions),
                         selectinload(tblCharacters.skills))
                .filter(tblCharacters.character_id.in_(char_ids)).all())
        chars = {c.character_id: c for c in rows}
    return monsters, chars


def _token_relay_payload(t, bm, monsters, chars):
    char = chars.get(t.entity_id)    if t.entity_type == 'player'  else None
    sm   = monsters.get(t.entity_id) if t.entity_type == 'monster' else None
    if t.entity_type == 'player' and not char:
        return None
    if t.entity_type == 'monster' and not sm:
        return None
    data = {
        'token_id':    t.token_id,
        'entity_type': t.entity_type,
        'entity_id':   t.entity_id,
        'col':         t.col,
        'row':         t.row,
        'x_pct':       t.col / max(1, bm.grid_cols - 1),
        'y_pct':       t.row / max(1, bm.grid_rows - 1),
        'label':       '',
        'token_type':  t.entity_type,
        'character_id': None,
        'image_url':   '',
        'size_squares': 1,
    }
    if char:
        data['label']      = char.name
        data['character_id'] = t.entity_id
        data['hp_current'] = char.hp_current
        data['hp_max']     = char.hp_max
    elif sm:
        stats = _monster_stats(sm)
        data['label']      = sm.display_name
        data['hp_current'] = sm.hp_current
        data['hp_max']     = sm.hp_max
        data['size_squares'] = _size_squares(sm.template.size if sm.template else '')
        data['conditions'] = json.loads(sm.conditions or '[]')
        if stats['image']:
            data['image_url'] = _monster_relay_img(stats['image'])
        data['speed'] = stats['speed']
        data['type']  = stats['type']
        data['ac']    = stats['ac']
    return data


def _is_live_map(bm):
    """True only if bm is the active map of the currently ACTIVE session."""
    if not bm or not bm.is_active:
        return False
    active_session = tblSessions.query.filter_by(status='active').first()
    return bool(active_session and bm.session_id == active_session.session_id)


def _push_map_state(bm):
    # Only the live map of the ACTIVE session is mirrored to the relay.
    if not _is_live_map(bm):
        return
    bg_url = _bg_url(bm, external=True)
    effects = [{
        'effect_id':    e.effect_id,
        'shape':        e.shape,
        'label':        e.label or '',
        'anchor_x':     e.anchor_x,
        'anchor_y':     e.anchor_y,
        'size_ft':      e.size_ft,
        'angle':        e.angle,
        'fill_color':   e.fill_color,
        'fill_opacity': e.fill_opacity,
        'border_color': e.border_color,
    } for e in bm.effects]
    monsters, chars = _fetch_token_entities(bm.tokens)
    floorplan = fp_version = doors = None
    fp = tblBattleMapFloorplans.query.filter_by(map_id=bm.map_id).first()
    if fp:
        try:
            floorplan = json.loads(fp.json_data)
        except (ValueError, TypeError):
            floorplan = None
        if floorplan is not None:
            fp_version = fp.version
            doors = {d.door_key: d.is_open
                     for d in tblBattleMapDoors.query.filter_by(map_id=bm.map_id)}
    textures = None
    if floorplan is not None:
        names = set()
        for w in floorplan.get('walls', []):
            if w.get('texture'):
                names.add(w['texture'])
        for dr in floorplan.get('doors', []):
            if dr.get('texture'):
                names.add(dr['texture'])
        for z in floorplan.get('zones', []):
            for key in floorplan_mod.ZONE_TEXTURE_KEYS:
                if z.get(key):
                    names.add(z[key])
        for pr in floorplan.get('props', []):
            name = pr.get('texture') or \
                floorplan_mod.PROP_DEFAULT_TEXTURES.get(pr.get('type'))
            if name:
                names.add(name)
        if names:
            from routers.textures import texture_paths
            textures = texture_paths(sorted(names)[:20]) or None
    relay_broadcaster.broadcast_map_update(
        bg_url, bm.grid_cols, bm.grid_rows,
        [p for p in (_token_relay_payload(t, bm, monsters, chars) for t in bm.tokens) if p],
        effects=effects,
        movement_scale=bm.movement_scale or 1.0,
        bg_filename=bm.bg_image,
        floorplan=floorplan, floorplan_version=fp_version, doors=doors,
        textures=textures,
    )


def _allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


def _delete_bg_file(filename, map_id=None):
    """Remove a map's background file — never a shared reference, and never
    a file another record still points at (see shared_assets)."""
    import media.shared_assets as shared_assets
    from extensions import database
    if not filename or shared_assets.is_ref(filename):
        return
    if shared_assets.referenced_elsewhere(database, 'battlemaps', filename,
                                          exclude=('tblBattleMaps', 'map_id', map_id)):
        return
    path = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(path):
        os.remove(path)


def _map_brief(m, index=None):
    ext = m.bg_image.rsplit('.', 1)[-1].lower() if m.bg_image and '.' in m.bg_image else ''
    return {'map_id': m.map_id, 'session_id': m.session_id, 'name': m.name, 'grid_cols': m.grid_cols,
            'grid_rows': m.grid_rows, 'bg_image': m.bg_image or '', 'bg_url': _bg_url(m),
            'bg_is_video': ext in VIDEO_EXT, 'is_active': m.is_active, 'sort_order': m.sort_order,
            'movement_scale': m.movement_scale or 1.0, 'token_count': len(m.tokens),
            'index': index}


def _session_brief(s):
    return {'session_id': s.session_id, 'title': s.title, 'session_number': s.session_number,
            'status': s.status, 'campaign_id': s.campaign_id, 'game': s.game_info(),
            'campaign_name': s.campaign.campaign_name if s.campaign else None}


def _active_map():
    active_session = tblSessions.query.filter_by(status='active').first()
    if not active_session:
        return None
    return tblBattleMaps.query.filter_by(session_id=active_session.session_id, is_active=1).first()


# ── page data ─────────────────────────────────────────────────────────────────

@api.get('/overview')
def all_maps(user=Depends(require_dm)):
    sessions = (tblSessions.query
                .join(tblBattleMaps, tblBattleMaps.session_id == tblSessions.session_id)
                .order_by(tblSessions.created_at.desc())
                .distinct()
                .all())
    out = []
    for s in sessions:
        maps = (tblBattleMaps.query.filter_by(session_id=s.session_id)
                .order_by(tblBattleMaps.sort_order, tblBattleMaps.map_id).all())
        out.append(dict(_session_brief(s), maps=[_map_brief(m, i + 1) for i, m in enumerate(maps)]))
    return {'sessions': out}


@api.get('/active')
def active_map(user=Depends(require_user)):
    bm = _active_map()
    return {'map_id': bm.map_id if bm else None, 'is_dm': user.is_dm(),
            'message': None if bm else 'No active battle map right now.'}


@api.get('/session/{session_id}/page')
def session_maps(session_id: int, user=Depends(require_dm)):
    sess = tblSessions.query.get_or_404(session_id)
    maps = (tblBattleMaps.query
            .filter_by(session_id=session_id)
            .order_by(tblBattleMaps.sort_order, tblBattleMaps.map_id)
            .all())
    ids = [m.map_id for m in maps] or [0]
    note_counts = dict(
        db.session.query(tblBattleMapNotes.map_id, db.func.count())
        .filter(tblBattleMapNotes.map_id.in_(ids))
        .group_by(tblBattleMapNotes.map_id).all())
    floorplan_info = {}
    for fp in tblBattleMapFloorplans.query.filter(tblBattleMapFloorplans.map_id.in_(ids)).all():
        try:
            summary = floorplan_mod.floorplan_summary(json.loads(fp.json_data))
        except (ValueError, TypeError):
            summary = ''
        floorplan_info[fp.map_id] = {'version': fp.version, 'summary': summary}
    from ttrpg.genre_packs import map_prompt_client_data
    rows = []
    for i, m in enumerate(maps):
        d = _map_brief(m, i + 1)
        d['note_count'] = note_counts.get(m.map_id, 0)
        d['floorplan'] = floorplan_info.get(m.map_id)
        rows.append(d)
    return {'sess': _session_brief(sess), 'maps': rows, 'map_prompt_data': map_prompt_client_data()}


def _roller_char(char):
    return {
        'id':   char.character_id,
        'name': char.name,
        'game_system': getattr(char, 'game_system', 'dnd5e') or 'dnd5e',
        'mods': {'STR': char.modifier(char.str_val), 'DEX': char.modifier(char.dex_val),
                 'CON': char.modifier(char.con_val), 'INT': char.modifier(char.int_val),
                 'WIS': char.modifier(char.wis_val), 'CHA': char.modifier(char.cha_val)},
        'prof': ((char.level - 1) // 4) + 2,
        'scores': {'STR': char.str_val, 'DEX': char.dex_val, 'CON': char.con_val,
                   'INT': char.int_val, 'WIS': char.wis_val, 'CHA': char.cha_val},
        'skills': [{'name': s.skill_name, 'bonus': s.bonus or 0, 'proficient': bool(s.proficient)}
                   for s in sorted(char.skills, key=lambda x: x.order_by)],
        'weapons': [{'name': w.weapon_name, 'dice': w.damage_dice or '', 'dmg_bonus': w.damage_bonus or 0,
                     'atk_bonus': w.attack_bonus or 0, 'dmg_type': w.damage_type or ''}
                    for w in sorted(char.weapons, key=lambda x: x.order_by)],
        'spells': [{'name': cs.spell_name, 'dice': (cs.lib_spell.damage_dice if cs.lib_spell else '') or '',
                    'level': cs.spell_level, 'prepared': bool(cs.prepared)}
                   for cs in sorted(char.spells, key=lambda x: (x.spell_level, x.order_by))],
        'hotlist': [{'id': i.item_id, 'name': i.item_name, 'qty': i.quantity or 1, 'notes': i.notes or ''}
                    for i in sorted(char.inventory, key=lambda x: x.order_by)
                    if getattr(i, 'hotlist', 0)]
                   if (getattr(char, 'game_system', 'dnd5e') or 'dnd5e') == 'dcc' else [],
    }


@api.get('/{map_id}/page')
def map_view(map_id: int, user=Depends(require_user)):
    bm   = tblBattleMaps.query.get_or_404(map_id)
    sess = db.session.get(tblSessions, bm.session_id)
    is_dm = user.is_dm()
    if not is_dm:
        active_session = tblSessions.query.filter_by(status='active').first()
        if (not active_session or sess is None
                or sess.session_id != active_session.session_id or not bm.is_active):
            live = _active_map()
            if live:
                return {'redirect_map_id': live.map_id}
            return {'redirect': '/ttrpg/my-character', 'message': 'No active battle map right now.'}

    monsters, party, on_map_monster_ids, on_map_player_ids = [], [], set(), set()
    if is_dm:
        monsters = (tblSessionMonsters.query
                    .filter_by(session_id=bm.session_id, is_alive=1)
                    .order_by(tblSessionMonsters.sort_order).all())
        party = [sp.character for sp in sess.party if sp.character]
        for t in bm.tokens:
            if t.entity_type == 'monster':
                on_map_monster_ids.add(t.entity_id)
            else:
                on_map_player_ids.add(t.entity_id)

    campaign_scenes = []
    if sess and sess.campaign_id:
        campaign_scenes = (tblscenes.query.filter_by(campaign_id=sess.campaign_id, active=1)
                           .order_by(tblscenes.orderBy).all())
    try:
        current_vol = currentvolume()
    except Exception:
        current_vol = 50

    roller_name = user.display_name
    if not is_dm:
        for sp in sess.party:
            if sp.character and sp.character.user_id == user.user_id:
                roller_name = sp.character.name
                break
    roller_chars = [_roller_char(sp.character) for sp in sess.party
                    if sp.character and (is_dm or sp.character.user_id == user.user_id)] if sess else []

    if is_dm and bm.is_active:
        _push_map_state(bm)

    fp = (tblBattleMapFloorplans.query.with_entities(tblBattleMapFloorplans.version)
          .filter_by(map_id=map_id).first())
    floorplan_version = fp.version if fp else None
    bm3d_available = bool(floorplan_version and bm.bg_image)

    obs_enabled = is_dm and appsettingGet('obs_enabled', '0') == '1'
    obs_scene_map, obs_scene_links, obs_links_live = {}, {}, False
    if is_dm:
        try:
            from routers.obs import scene_link_map, scene_links_live
            obs_scene_links = scene_link_map()
            obs_links_live = scene_links_live()
        except Exception:
            pass
    if obs_enabled:
        from models.ttrpg import tblObsSceneMap
        obs_scene_map = {r.entity_id: r.scene_name for r in
                         tblObsSceneMap.query.filter_by(entity_type='player').all()}

    from routers.ttrpg import char_brief
    mon_rows = []
    for m in monsters:
        stats = _monster_stats(m)
        mon_rows.append({'monster_id': m.monster_id, 'display_name': m.display_name, 'hp_current': m.hp_current,
                         'hp_max': m.hp_max, 'hp_pct': m.hp_pct(), 'template_id': m.template_id,
                         'size': m.template.size if m.template else '', 'image': _monster_img_url(stats['image']),
                         'on_map': m.monster_id in on_map_monster_ids})
    party_rows = []
    for c in party:
        d = char_brief(c)
        d['on_map'] = c.character_id in on_map_player_ids
        d['obs_scene'] = obs_scene_map.get(c.character_id)
        party_rows.append(d)
    return {
        'bm': _map_brief(bm), 'sess': _session_brief(sess) if sess else None,
        'game': tblSessions.active_game_info(), 'collapse': _collapse_state(bm),
        'monsters': mon_rows, 'party': party_rows,
        'on_map_monster_ids': sorted(on_map_monster_ids), 'on_map_player_ids': sorted(on_map_player_ids),
        'cell_px': CELL_PX, 'roller_name': roller_name, 'roller_chars': roller_chars,
        'campaign_scenes': [{'scene_ID': s.scene_ID, 'sceneName': s.sceneName,
                             'obs_scene': (obs_scene_links or {}).get(s.scene_ID)} for s in campaign_scenes],
        'current_vol': current_vol, 'floorplan_version': floorplan_version, 'bm3d_available': bm3d_available,
        'obs_enabled': obs_enabled, 'obs_scene_map': {str(k): v for k, v in obs_scene_map.items()},
        'obs_links_live': obs_links_live, 'is_dm': is_dm, 'current_user_id': user.user_id,
        'bg_url': _bg_url(bm),
    }


# ── Map manager (DM) ──────────────────────────────────────────────────────────

@router.post('/session/{session_id}/new')
def map_new(session_id: int, form: dict = Depends(form_or_json), user=Depends(require_dm)):
    tblSessions.query.get_or_404(session_id)
    name = (form.get('name') or '').strip() or 'Untitled Map'
    cols = max(5, min(60, int(form.get('cols', 20) or 20)))
    rows = max(5, min(60, int(form.get('rows', 20) or 20)))
    next_order = (db.session.query(db.func.max(tblBattleMaps.sort_order))
                  .filter_by(session_id=session_id).scalar() or 0) + 1
    bm = tblBattleMaps(session_id=session_id, name=name, grid_cols=cols, grid_rows=rows,
                       bg_image='', is_active=0, sort_order=next_order, created_at=_now())
    db.session.add(bm)
    db.session.commit()
    return {'ok': True, 'map_id': bm.map_id, 'message': f'Map "{name}" created.'}


@router.post('/{map_id}/reorder')
def map_reorder(map_id: int, form: dict = Depends(form_or_json), user=Depends(require_dm)):
    """Move a map one step earlier/later in the DM's display order."""
    bm = tblBattleMaps.query.get_or_404(map_id)
    direction = form.get('direction', '')
    maps = (tblBattleMaps.query.filter_by(session_id=bm.session_id)
            .order_by(tblBattleMaps.sort_order, tblBattleMaps.map_id).all())
    for i, m in enumerate(maps):
        m.sort_order = i
    idx = next((i for i, m in enumerate(maps) if m.map_id == map_id), None)
    if idx is not None:
        swap = idx - 1 if direction == 'up' else idx + 1 if direction == 'down' else None
        if swap is not None and 0 <= swap < len(maps):
            maps[idx].sort_order, maps[swap].sort_order = maps[swap].sort_order, maps[idx].sort_order
    db.session.commit()
    return {'ok': True}


@router.post('/{map_id}/activate')
def map_activate(map_id: int, user=Depends(require_dm)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    tblBattleMaps.query.filter_by(session_id=bm.session_id).update({'is_active': 0})
    bm.is_active = 1
    db.session.commit()
    _push_map_state(bm)
    activation_ts = datetime.now(timezone.utc).isoformat()
    for t in bm.tokens:
        t.updated_at = activation_ts
    db.session.commit()
    from models.tblTokenPositions import tblTokenPositions
    tblTokenPositions.query.filter_by(session_id=bm.session_id).delete(synchronize_session=False)
    db.session.commit()
    _emit(bm.map_id, 'activate')
    return {'ok': True, 'map_id': bm.map_id, 'name': bm.name, 'message': f'"{bm.name}" is now the active map.'}


@router.post('/{map_id}/delete')
def map_delete(map_id: int, user=Depends(require_dm)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    _delete_bg_file(bm.bg_image, bm.map_id)
    db.session.delete(bm)
    db.session.commit()
    return {'ok': True, 'message': 'Map deleted.'}


@router.post('/{map_id}/edit')
def map_edit(map_id: int, form: dict = Depends(form_or_json), user=Depends(require_dm)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    name = (form.get('name') or '').strip()
    if name:
        bm.name = name
    cols = max(5, min(60, int(form.get('cols', bm.grid_cols) or bm.grid_cols)))
    rows = max(5, min(60, int(form.get('rows', bm.grid_rows) or bm.grid_rows)))
    bm.grid_cols = cols
    bm.grid_rows = rows
    for t in bm.tokens:
        changed = False
        if t.col >= cols:
            t.col = cols - 1
            changed = True
        if t.row >= rows:
            t.row = rows - 1
            changed = True
        if changed:
            t.updated_at = datetime.now(timezone.utc).isoformat()
    db.session.commit()
    _push_map_state(bm)
    _emit(bm.map_id, 'edit')
    return {'ok': True, 'message': f'Map "{bm.name}" updated.'}


@router.post('/{map_id}/bg')
def map_bg(map_id: int, form: dict = Depends(form_or_json), bg_image: UploadFile = File(None),
           user=Depends(require_dm)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    f = bg_image
    ref = (form.get('bg_ref') or '').strip()
    if not (f and f.filename) and ref:
        import media.shared_assets as shared_assets
        from extensions import database
        if not shared_assets.valid_ref(config.ROOT, database, 'battlemaps', ref) \
                and not (('/' not in ref) and os.path.isfile(os.path.join(UPLOAD_FOLDER, ref))):
            return _bad('That file is not available.')
        _delete_bg_file(bm.bg_image, bm.map_id)
        bm.bg_image = ref
        db.session.commit()
        _push_map_state(bm)
        _emit(bm.map_id, 'bg')
        return {'ok': True, 'message': 'Background set to an existing file.', 'url': _bg_url(bm)}
    if f and f.filename and _allowed(f.filename):
        _delete_bg_file(bm.bg_image, bm.map_id)
        ext = f.filename.rsplit('.', 1)[1].lower()
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        if ext in VIDEO_EXT:
            filename = f'{uuid.uuid4().hex}.{ext}'
            with open(os.path.join(UPLOAD_FOLDER, filename), 'wb') as fh:
                shutil.copyfileobj(f.file, fh)
        else:
            filename = save_upload_downscaled(f, UPLOAD_FOLDER, max_dim=2048)
        bm.bg_image = filename
        db.session.commit()
        _push_map_state(bm)
        _emit(bm.map_id, 'bg')
        return {'ok': True, 'message': 'Background image updated.', 'url': _bg_url(bm)}
    return {'ok': False, 'error': 'no file'}


def _store_bg_bytes(bm, raw, ext):
    """Store raw bytes as a map's background: delete the old file, downscale
    still images to 2048px (videos pass through untouched), commit, push to
    the relay. Shared by the clipboard paste and the AI-generation routes."""
    ext = (ext or 'png').lower()
    if ext not in ALLOWED_EXT:
        ext = 'png'
    _delete_bg_file(bm.bg_image, bm.map_id)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    is_video = ext in VIDEO_EXT
    if is_video:
        filename = f'{uuid.uuid4().hex}.{ext}'
        with open(os.path.join(UPLOAD_FOLDER, filename), 'wb') as fh:
            fh.write(raw)
    else:
        from integrations.relay_broadcaster import _downscale_image
        out, out_ext = _downscale_image(raw, ext, 2048)
        filename = f'{uuid.uuid4().hex}.{out_ext}'
        with open(os.path.join(UPLOAD_FOLDER, filename), 'wb') as fh:
            fh.write(out)
    bm.bg_image = filename
    db.session.commit()
    url = static_url('uploads/battlemaps/' + filename)
    _push_map_state(bm)
    _emit(bm.map_id, 'bg')
    return {'ok': True, 'url': url, 'is_video': is_video, 'filename': filename}


@router.post('/{map_id}/bg-paste')
def map_bg_paste(map_id: int, form: dict = Depends(form_or_json), bg_image: UploadFile = File(None),
                 user=Depends(require_dm)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    if bg_image is None:
        return _bad('no file')
    ext = (form.get('ext') or 'png').lower()
    return _store_bg_bytes(bm, bg_image.file.read(), ext)


@router.get('/api/maps')
def api_maps_list(user=Depends(require_dm)):
    """Flat map list for pickers (e.g. the video table's 'use as map bg')."""
    rows = (db.session.query(tblBattleMaps, tblSessions)
            .join(tblSessions, tblBattleMaps.session_id == tblSessions.session_id)
            .order_by(tblSessions.created_at.desc(), tblBattleMaps.sort_order, tblBattleMaps.map_id)
            .all())
    return [{'map_id': bm.map_id, 'name': bm.name, 'session': f'#{s.session_number} — {s.title}'}
            for bm, s in rows]


@router.post('/{map_id}/bg-from-library')
def map_bg_from_library(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    """Set a map's background from a video-library row (server-side copy)."""
    bm = tblBattleMaps.query.get_or_404(map_id)
    from models.videoMedia import tblvideomedia
    row = db.session.get(tblvideomedia, data.get('video_ID'))
    if row is None:
        return _bad('video row not found', 404)
    fname = row.title or ''
    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
    if ext not in ALLOWED_EXT:
        return _bad(f'unsupported file type "{ext}"')
    src = (row.path or '') + fname
    if not os.path.isfile(src):
        return _bad('file not on disk yet — has the download finished?', 404)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.{ext}'
    shutil.copyfile(src, os.path.join(UPLOAD_FOLDER, filename))
    _delete_bg_file(bm.bg_image, bm.map_id)
    bm.bg_image = filename
    db.session.commit()
    _push_map_state(bm)
    _emit(bm.map_id, 'bg')
    return {'ok': True, 'map': bm.name, 'is_video': ext in VIDEO_EXT,
            'url': static_url('uploads/battlemaps/' + filename)}


@router.post('/{map_id}/bg/clear')
def map_bg_clear(map_id: int, user=Depends(require_dm)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    _delete_bg_file(bm.bg_image, bm.map_id)
    bm.bg_image = ''
    db.session.commit()
    _emit(bm.map_id, 'bg')
    return {'ok': True, 'message': 'Background cleared.'}


# ── Relay presence / roll feed proxy ─────────────────────────────────────────

@router.get('/relay-presence')
def relay_presence(user=Depends(require_dm)):
    return {'presence': relay_broadcaster.get_presence()}


@router.get('/relay-rolls')
def relay_rolls(since_id: int = 0, user=Depends(require_user)):
    return {'rolls': relay_broadcaster.get_relay_rolls(since_id)}


# ── State poll endpoint ───────────────────────────────────────────────────────

@router.get('/{map_id}/state')
def map_state(map_id: int, user=Depends(require_user)):
    bm     = tblBattleMaps.query.get_or_404(map_id)
    result = []
    monsters, chars = _fetch_token_entities(bm.tokens)
    for t in bm.tokens:
        if t.entity_type == 'monster':
            sm = monsters.get(t.entity_id)
            if not sm:
                continue
            stats = _monster_stats(sm)
            result.append({
                'token_id': t.token_id, 'entity_type': 'monster', 'entity_id': t.entity_id,
                'name': sm.display_name, 'col': t.col, 'row': t.row,
                'hp_current': sm.hp_current, 'hp_max': sm.hp_max, 'hp_pct': sm.hp_pct(),
                'is_alive': sm.is_alive, 'size_squares': _size_squares(sm.template.size if sm.template else ''),
                'image_url': _monster_img_url(stats['image']), 'color': '#cc3333',
                'conditions': json.loads(sm.conditions or '[]'), 'skills': [],
                'speed': stats['speed'], 'ac': stats['ac'],
            })
        elif t.entity_type == 'player':
            char = chars.get(t.entity_id)
            if not char:
                continue
            from routers.ttrpg import portrait_url
            result.append({
                'token_id': t.token_id, 'entity_type': 'player', 'entity_id': t.entity_id,
                'name': char.name, 'col': t.col, 'row': t.row,
                'hp_current': char.hp_current, 'hp_max': char.hp_max, 'hp_pct': char.hp_pct(),
                'is_alive': 1, 'size_squares': 1, 'image_url': portrait_url(char), 'color': '#4a9eff',
                'conditions': [c.condition_name for c in char.conditions],
                'skills': [{'name': s.skill_name, 'bonus': s.bonus, 'proficient': bool(s.proficient)}
                           for s in sorted(char.skills, key=lambda x: x.order_by)],
                'speed': char.speed, 'ac': char.ac, 'user_id': char.user_id,
            })

    effects = [{
        'effect_id': e.effect_id, 'shape': e.shape, 'label': e.label, 'anchor_x': e.anchor_x,
        'anchor_y': e.anchor_y, 'size_ft': e.size_ft, 'angle': e.angle, 'fill_color': e.fill_color,
        'fill_opacity': e.fill_opacity, 'border_color': e.border_color,
    } for e in bm.effects]

    active_session = tblSessions.query.filter_by(status='active').first()
    roller_sig = None
    if not user.is_dm() and active_session:
        ids = sorted(
            sp.character_id for sp in tblSessionParty.query
            .join(tblCharacters, tblCharacters.character_id == tblSessionParty.character_id)
            .filter(tblSessionParty.session_id == active_session.session_id,
                    tblCharacters.user_id == user.user_id,
                    tblCharacters.active == 1).all())
        roller_sig = ','.join(str(i) for i in ids)
    active_map_id = None
    if active_session:
        active_bm = tblBattleMaps.query.filter_by(session_id=active_session.session_id, is_active=1).first()
        if active_bm:
            active_map_id = active_bm.map_id

    fp = (tblBattleMapFloorplans.query.with_entities(tblBattleMapFloorplans.version)
          .filter_by(map_id=map_id).first())
    doors = None
    if fp:
        doors = {d.door_key: d.is_open for d in tblBattleMapDoors.query.filter_by(map_id=map_id).all()}

    return {
        'tokens': result, 'effects': effects, 'grid_cols': bm.grid_cols, 'grid_rows': bm.grid_rows,
        'active_map_id': active_map_id, 'roller_sig': roller_sig,
        'floorplan_version': fp.version if fp else None, 'doors': doors,
        'obs': _obs_poll_state(user), 'collapse': _collapse_state(bm),
    }


def _collapse_state(bm):
    import ttrpg.dice_systems as dice_systems
    sess = db.session.get(tblSessions, bm.session_id)
    return dice_systems.collapse_info(sess.game_info()) if sess else None


def _obs_poll_state(user):
    """OBS status for the DM's sidebar, or None when it isn't wanted (DM-only,
    in-memory read of obs_ws's event-fed cache). None until the OBS router
    is ported."""
    if not user.is_dm() or appsettingGet('obs_enabled', '0') != '1':
        return None
    try:
        import integrations.obs_ws as obs_ws
        snap = obs_ws.current_state()
        from routers.obs import (map_mode, viewed_character_id, CUT_TARGETS, _cut_scene_name,
                                 _muted_ids, auto_cam_setting, _card_overrides, _ordered_party)
    except Exception:
        return None
    return {'connected': snap['connected'], 'current_scene': snap['current_scene'],
            'recording': snap['recording'], 'streaming': snap['streaming'], 'map_mode': map_mode(),
            'cut_scenes': {k: _cut_scene_name(k) for k in CUT_TARGETS}, 'map_scene': _cut_scene_name('map'),
            'view_char': viewed_character_id(), 'muted_ids': sorted(_muted_ids()), 'auto_cam': auto_cam_setting(),
            'cards': _cards_state(_card_overrides(), _ordered_party())}


def _cards_state(pinned, party):
    ids = {c.character_id for c in party}
    if not ids or not (ids & pinned):
        return 'none'
    return 'all' if ids <= pinned else 'some'


# ── Token CRUD ────────────────────────────────────────────────────────────────

@router.post('/{map_id}/token/add')
def token_add(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    entity_type = data.get('entity_type')
    entity_id   = int(data.get('entity_id', 0) or 0)
    if entity_type not in ('monster', 'player') or not entity_id:
        return _bad('invalid entity')
    existing = tblBattleMapTokens.query.filter_by(map_id=map_id, entity_type=entity_type, entity_id=entity_id).first()
    if existing:
        return {'ok': False, 'error': 'already on map'}
    t = tblBattleMapTokens(map_id=map_id, entity_type=entity_type, entity_id=entity_id,
                           col=0, row=0, updated_at=datetime.now(timezone.utc).isoformat())
    db.session.add(t)
    db.session.commit()
    _push_map_state(bm)
    _emit(map_id, 'token')
    return {'ok': True, 'token_id': t.token_id}


@router.post('/{map_id}/token/remove')
def token_remove(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    t = tblBattleMapTokens.query.get_or_404(data.get('token_id'))
    if t.map_id != map_id:
        return JSONResponse({'ok': False}, status_code=403)
    db.session.delete(t)
    db.session.commit()
    bm = db.session.get(tblBattleMaps, map_id)
    if bm:
        _push_map_state(bm)
    _emit(map_id, 'token')
    return {'ok': True}


@router.post('/{map_id}/token/move')
def token_move(map_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    t  = tblBattleMapTokens.query.get_or_404(data.get('token_id'))
    if t.map_id != map_id:
        return JSONResponse({'ok': False}, status_code=403)
    if not user.is_dm():
        if t.entity_type != 'player':
            return JSONResponse({'ok': False}, status_code=403)
        char = db.session.get(tblCharacters, t.entity_id)
        if not char or char.user_id != user.user_id:
            return JSONResponse({'ok': False}, status_code=403)
    t.col = max(0, min(bm.grid_cols - 1, int(data.get('col', t.col))))
    t.row = max(0, min(bm.grid_rows - 1, int(data.get('row', t.row))))
    t.updated_at = datetime.now(timezone.utc).isoformat()
    db.session.commit()
    label = ''
    character_id = None
    if t.entity_type == 'player':
        char = db.session.get(tblCharacters, t.entity_id)
        if char:
            label = char.name
            character_id = t.entity_id
    elif t.entity_type == 'monster':
        sm = db.session.get(tblSessionMonsters, t.entity_id)
        if sm:
            label = sm.display_name
    x_pct = t.col / max(1, bm.grid_cols - 1)
    y_pct = t.row / max(1, bm.grid_rows - 1)
    if _is_live_map(bm) and label:
        relay_broadcaster.broadcast_token_move(t.token_id, x_pct, y_pct, label=label,
                                               token_type=t.entity_type, character_id=character_id)
    _emit(map_id, 'move')
    return {'ok': True, 'col': t.col, 'row': t.row}


@router.post('/{map_id}/movement-scale')
def set_movement_scale(map_id: int, data: dict = Depends(json_body), user=Depends(require_user)):
    """GM-only: save the per-map feet-per-square multiplier for the move radius."""
    if not user.is_dm():
        return JSONResponse({'ok': False}, status_code=403)
    bm = tblBattleMaps.query.get_or_404(map_id)
    try:
        scale = float(data.get('movement_scale', 1.0))
    except (TypeError, ValueError, AttributeError):
        scale = 1.0
    bm.movement_scale = max(0.05, min(20.0, scale))
    db.session.commit()
    if bm.is_active:
        _push_map_state(bm)
    _emit(map_id, 'scale')
    return {'ok': True, 'movement_scale': bm.movement_scale}


# ── Effect CRUD ───────────────────────────────────────────────────────────────

@router.post('/{map_id}/effect/add')
def effect_add(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    tblBattleMaps.query.get_or_404(map_id)
    shape = data.get('shape', 'circle')
    if shape not in ('circle', 'cone', 'line', 'square', 'cloud'):
        return _bad('invalid shape')
    e = tblBattleMapEffects(
        map_id=map_id, shape=shape, label=(data.get('label') or '').strip()[:40],
        anchor_x=float(data.get('anchor_x', 0)), anchor_y=float(data.get('anchor_y', 0)),
        size_ft=max(5, int(data.get('size_ft', 20))), angle=float(data.get('angle', 0)),
        fill_color=data.get('fill_color', '#ff4400'),
        fill_opacity=max(0.05, min(1.0, float(data.get('fill_opacity', 0.35)))),
        border_color=data.get('border_color', '#ff8800'), created_at=_now(),
    )
    db.session.add(e)
    db.session.commit()
    _push_map_state(db.session.get(tblBattleMaps, map_id))
    _emit(map_id, 'effect')
    return {'ok': True, 'effect_id': e.effect_id}


@router.post('/{map_id}/effect/{effect_id}/update')
def effect_update(map_id: int, effect_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    e = tblBattleMapEffects.query.get_or_404(effect_id)
    if e.map_id != map_id:
        return JSONResponse({'ok': False}, status_code=403)
    if 'anchor_x'     in data: e.anchor_x     = float(data['anchor_x'])
    if 'anchor_y'     in data: e.anchor_y     = float(data['anchor_y'])
    if 'angle'        in data: e.angle        = float(data['angle'])
    if 'size_ft'      in data: e.size_ft      = max(5, int(data['size_ft']))
    if 'fill_color'   in data: e.fill_color   = data['fill_color']
    if 'fill_opacity' in data: e.fill_opacity = max(0.05, min(1.0, float(data['fill_opacity'])))
    if 'border_color' in data: e.border_color = data['border_color']
    if 'label'        in data: e.label        = data['label'].strip()[:40]
    db.session.commit()
    _push_map_state(db.session.get(tblBattleMaps, map_id))
    _emit(map_id, 'effect')
    return {'ok': True}


@router.post('/{map_id}/effect/{effect_id}/delete')
def effect_delete(map_id: int, effect_id: int, user=Depends(require_dm)):
    e = tblBattleMapEffects.query.get_or_404(effect_id)
    if e.map_id != map_id:
        return JSONResponse({'ok': False}, status_code=403)
    db.session.delete(e)
    db.session.commit()
    _push_map_state(db.session.get(tblBattleMaps, map_id))
    _emit(map_id, 'effect')
    return {'ok': True}


@router.post('/{map_id}/effect/clear')
def effect_clear(map_id: int, user=Depends(require_dm)):
    tblBattleMaps.query.get_or_404(map_id)
    tblBattleMapEffects.query.filter_by(map_id=map_id).delete()
    db.session.commit()
    _push_map_state(db.session.get(tblBattleMaps, map_id))
    _emit(map_id, 'effect')
    return {'ok': True}


# ── Floorplan (3D-mode geometry) ─────────────────────────────────────────────

@router.get('/{map_id}/floorplan')
def floorplan_get(map_id: int, user=Depends(require_user)):
    tblBattleMaps.query.get_or_404(map_id)
    fp = tblBattleMapFloorplans.query.filter_by(map_id=map_id).first()
    if not fp:
        return {'ok': True, 'version': None, 'floorplan': None}
    plan = json.loads(fp.json_data)
    return {'ok': True, 'version': fp.version, 'floorplan': plan,
            'layout_text': floorplan_mod.floorplan_layout_text(plan)}


def _unknown_texture_refs(clean):
    """Texture slugs the plan references that the library doesn't have."""
    from routers.textures import texture_names
    have = set(texture_names())
    refs = set()
    for w in clean.get('walls', []):
        if w.get('texture'):
            refs.add(w['texture'])
    for d in clean.get('doors', []):
        if d.get('texture'):
            refs.add(d['texture'])
    for p in clean.get('props', []):
        if p.get('texture'):
            refs.add(p['texture'])
    for z in clean.get('zones', []):
        for key in floorplan_mod.ZONE_TEXTURE_KEYS:
            if z.get(key):
                refs.add(z[key])
    return sorted(refs - have)


@router.post('/{map_id}/floorplan')
def floorplan_save(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    bm = tblBattleMaps.query.get_or_404(map_id)
    clean, warnings, errors = floorplan_mod.validate_floorplan(data.get('floorplan'), bm.grid_cols, bm.grid_rows)
    if errors:
        return JSONResponse({'ok': False, 'errors': errors}, status_code=400)
    if data.get('dry_run'):
        return {'ok': True, 'dry_run': True, 'warnings': warnings,
                'summary': floorplan_mod.floorplan_summary(clean),
                'unknown_textures': _unknown_texture_refs(clean), 'floorplan': clean}
    return _apply_floorplan(bm, clean, warnings)


FLOORPLAN_HISTORY_KEEP = 10


def _apply_floorplan(bm, clean, warnings):
    """Store a validated plan: snapshot the outgoing JSON to history, bump the
    version, reconcile door rows, push to the relay. Shared by save/restore."""
    from models.ttrpg import tblBattleMapFloorplanHistory
    map_id = bm.map_id
    fp = tblBattleMapFloorplans.query.filter_by(map_id=map_id).first()
    if fp:
        db.session.add(tblBattleMapFloorplanHistory(map_id=map_id, version=fp.version or 1,
                                                    json_data=fp.json_data, saved_at=_now()))
        overflow = (tblBattleMapFloorplanHistory.query.filter_by(map_id=map_id)
                    .order_by(tblBattleMapFloorplanHistory.hist_id.desc())
                    .offset(FLOORPLAN_HISTORY_KEEP).all())
        for row in overflow:
            db.session.delete(row)
        fp.json_data  = json.dumps(clean)
        fp.version    = (fp.version or 1) + 1
        fp.updated_at = _now()
    else:
        fp = tblBattleMapFloorplans(map_id=map_id, json_data=json.dumps(clean), version=1, updated_at=_now())
        db.session.add(fp)
    existing = {d.door_key: d for d in tblBattleMapDoors.query.filter_by(map_id=map_id).all()}
    new_ids = {d['id'] for d in clean['doors']}
    for door in clean['doors']:
        if door['id'] not in existing:
            db.session.add(tblBattleMapDoors(map_id=map_id, door_key=door['id'],
                                             is_open=1 if door.get('open') else 0, updated_at=_now()))
    for key, row in existing.items():
        if key not in new_ids:
            db.session.delete(row)
    db.session.commit()
    _push_map_state(bm)
    _emit(map_id, 'floorplan')
    return {'ok': True, 'version': fp.version, 'warnings': warnings,
            'summary': floorplan_mod.floorplan_summary(clean), 'floorplan': clean}


@router.get('/{map_id}/floorplan/history')
def floorplan_history(map_id: int, user=Depends(require_dm)):
    from models.ttrpg import tblBattleMapFloorplanHistory
    tblBattleMaps.query.get_or_404(map_id)
    out = []
    rows = (tblBattleMapFloorplanHistory.query.filter_by(map_id=map_id)
            .order_by(tblBattleMapFloorplanHistory.hist_id.desc()).all())
    for row in rows:
        try:
            summary = floorplan_mod.floorplan_summary(json.loads(row.json_data))
        except (ValueError, TypeError):
            summary = '(unreadable)'
        out.append({'hist_id': row.hist_id, 'version': row.version, 'saved_at': row.saved_at, 'summary': summary})
    return {'ok': True, 'history': out}


@router.post('/{map_id}/floorplan/restore')
def floorplan_restore(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    from models.ttrpg import tblBattleMapFloorplanHistory
    bm = tblBattleMaps.query.get_or_404(map_id)
    hist_id = data.get('hist_id')
    row = tblBattleMapFloorplanHistory.query.filter_by(map_id=map_id, hist_id=hist_id).first()
    if row is None:
        return JSONResponse({'ok': False, 'errors': ['unknown history entry']}, status_code=404)
    try:
        raw = json.loads(row.json_data)
    except (ValueError, TypeError):
        return JSONResponse({'ok': False, 'errors': ['stored snapshot is unreadable']}, status_code=400)
    clean, warnings, errors = floorplan_mod.validate_floorplan(raw, bm.grid_cols, bm.grid_rows)
    if errors:
        return JSONResponse({'ok': False, 'errors': errors}, status_code=400)
    return _apply_floorplan(bm, clean, warnings)


@router.post('/{map_id}/floorplan/delete')
def floorplan_delete(map_id: int, user=Depends(require_dm)):
    tblBattleMaps.query.get_or_404(map_id)
    tblBattleMapFloorplans.query.filter_by(map_id=map_id).delete()
    tblBattleMapDoors.query.filter_by(map_id=map_id).delete()
    db.session.commit()
    _push_map_state(db.session.get(tblBattleMaps, map_id))
    _emit(map_id, 'floorplan')
    return {'ok': True}


# ── Stored LLM prompts ────────────────────────────────────────────────────────

PROMPT_KINDS = ('art', 'layout')
MAX_PROMPT_BYTES = 64 * 1024


@router.post('/{map_id}/prompt')
def prompt_save(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    tblBattleMaps.query.get_or_404(map_id)
    kind = data.get('kind')
    text = (data.get('prompt_text') or '').strip()
    if kind not in PROMPT_KINDS or not text:
        return _bad('kind must be art|layout and prompt_text non-empty')
    if len(text.encode('utf-8')) > MAX_PROMPT_BYTES:
        return _bad(f'prompt too large (> {MAX_PROMPT_BYTES // 1024} KB)')
    settings = json.dumps(data.get('settings') or {})
    row = tblBattleMapPrompts.query.filter_by(map_id=map_id, kind=kind).first()
    if row:
        row.prompt_text, row.settings_json, row.updated_at = text, settings, _now()
    else:
        db.session.add(tblBattleMapPrompts(map_id=map_id, kind=kind, prompt_text=text,
                                           settings_json=settings, updated_at=_now()))
    db.session.commit()
    return {'ok': True}


@router.get('/{map_id}/prompts')
def prompts_get(map_id: int, user=Depends(require_user)):
    tblBattleMaps.query.get_or_404(map_id)
    out = {k: None for k in PROMPT_KINDS}
    for row in tblBattleMapPrompts.query.filter_by(map_id=map_id).all():
        if row.kind in out:
            try:
                settings = json.loads(row.settings_json or '{}')
            except ValueError:
                settings = {}
            out[row.kind] = {'prompt_text': row.prompt_text, 'settings': settings, 'updated_at': row.updated_at}
    return {'ok': True, **out}


@router.post('/{map_id}/door/toggle')
def door_toggle(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    tblBattleMaps.query.get_or_404(map_id)
    key = (data.get('door_key') or '').strip()
    d = tblBattleMapDoors.query.filter_by(map_id=map_id, door_key=key).first()
    if not d:
        return _bad('unknown door', 404)
    d.is_open = 0 if d.is_open else 1
    d.updated_at = _now()
    db.session.commit()
    _push_map_state(db.session.get(tblBattleMaps, map_id))
    _emit(map_id, 'door')
    return {'ok': True, 'door_key': key, 'is_open': d.is_open}


# ── DM map notes ──────────────────────────────────────────────────────────────

@router.get('/{map_id}/notes/list')
def notes_list(map_id: int, user=Depends(require_dm)):
    tblBattleMaps.query.get_or_404(map_id)
    notes = (tblBattleMapNotes.query.filter_by(map_id=map_id)
             .order_by(tblBattleMapNotes.sort_order, tblBattleMapNotes.note_id.desc()).all())
    return {'ok': True, 'notes': [{'note_id': n.note_id, 'title': n.title, 'body': n.body,
                                   'updated_at': n.updated_at} for n in notes]}


@router.post('/{map_id}/notes/add')
def notes_add(map_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    tblBattleMaps.query.get_or_404(map_id)
    min_sort = (db.session.query(db.func.min(tblBattleMapNotes.sort_order)).filter_by(map_id=map_id).scalar())
    n = tblBattleMapNotes(map_id=map_id, title=(data.get('title') or '').strip()[:120], body=data.get('body') or '',
                          sort_order=(min_sort - 1) if min_sort is not None else 0,
                          created_at=_now(), updated_at=_now())
    db.session.add(n)
    db.session.commit()
    return {'ok': True, 'note_id': n.note_id}


@router.post('/{map_id}/notes/{note_id}/update')
def notes_update(map_id: int, note_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    n = tblBattleMapNotes.query.get_or_404(note_id)
    if n.map_id != map_id:
        return JSONResponse({'ok': False}, status_code=403)
    if 'title' in data:
        n.title = (data.get('title') or '').strip()[:120]
    if 'body' in data:
        n.body = data.get('body') or ''
    n.updated_at = _now()
    db.session.commit()
    return {'ok': True}


@router.post('/{map_id}/notes/{note_id}/reorder')
def notes_reorder(map_id: int, note_id: int, data: dict = Depends(json_body), user=Depends(require_dm)):
    n = tblBattleMapNotes.query.get_or_404(note_id)
    if n.map_id != map_id:
        return JSONResponse({'ok': False}, status_code=403)
    direction = data.get('direction', '')
    notes = (tblBattleMapNotes.query.filter_by(map_id=map_id)
             .order_by(tblBattleMapNotes.sort_order, tblBattleMapNotes.note_id.desc()).all())
    for i, x in enumerate(notes):
        x.sort_order = i
    idx = next((i for i, x in enumerate(notes) if x.note_id == note_id), None)
    if idx is not None:
        swap = idx - 1 if direction == 'up' else idx + 1 if direction == 'down' else None
        if swap is not None and 0 <= swap < len(notes):
            notes[idx].sort_order, notes[swap].sort_order = notes[swap].sort_order, notes[idx].sort_order
    db.session.commit()
    return {'ok': True}


@router.post('/{map_id}/notes/{note_id}/delete')
def notes_delete(map_id: int, note_id: int, user=Depends(require_dm)):
    n = tblBattleMapNotes.query.get_or_404(note_id)
    if n.map_id != map_id:
        return JSONResponse({'ok': False}, status_code=403)
    db.session.delete(n)
    db.session.commit()
    return {'ok': True}


@api.get('/monster-redirect/{monster_id}')
def monster_redirect(monster_id: int, user=Depends(require_dm)):
    """Where the SPA sends a monster-token click: the template's card with
    instance= so it shows THAT enemy's live HP."""
    sm = tblSessionMonsters.query.get_or_404(monster_id)
    return {'redirect': f'/ttrpg/monsters/{sm.template_id}/view?instance={sm.monster_id}'}


open_router = api   # /api/v1/battlemap page data
