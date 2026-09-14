"""Scenes table + the global campaign/scene filters + the home page data
(ported from routes/scenes_table.py and routes/main.home)."""
from fastapi import APIRouter, Depends, Response

from core.db import db
from extensions import currentvolume
from models.scenes import tblscenes as tbl
from routers._util import campaigns_for_filter, json_body, scenes_for_filter
from routers.tables._grid import paginate, sort_clause
from security.deps import ApiError, sceneplay_dm_gate
from sql import (CRUD_tblCampaigns, CRUD_tblScenes, appsettingGetCampaignFilter,
                 appsettingGetCampaignSelected, appsettingGetSceneFilter, appsettingSetCampaignFilter,
                 appsettingSetSceneFilter, get_Scenes, queue_scene_songs, scene_queue_state,
                 scene_queue_states, select_data_stats, set_scene_order)
import core.events as events

tblColumns = ['scene_ID', 'sceneName', 'active', 'orderBy', 'campaign_id']
primeKey = tblColumns[0]

open_router = APIRouter()
router = APIRouter(dependencies=[Depends(sceneplay_dm_gate)])


def _rows(query):
    """Scene rows + queue state + smart-scene rule summary."""
    import media.smart_scenes as smart_scenes
    from extensions import database
    rules = {x['scene_id']: x['summary'] for x in smart_scenes.list_rules(database)}
    rows = []
    for r in query:
        d = r.to_dict()
        d['queued'] = scene_queue_state(r.scene_ID)
        d['rule'] = rules.get(r.scene_ID, '')      # '' = a plain, hand-built scene
        rows.append(d)
    return rows


@open_router.get('/api/scenes')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    """The browser extension reads this without a session (it stays open even
    under the DM-only switch); every edit endpoint below is gated."""
    query = tbl.query
    sceneF = int(appsettingGetSceneFilter()[0][0])
    campaign = appsettingGetCampaignFilter()
    if sceneF:
        query = query.filter(tbl.scene_ID == sceneF)
    elif campaign:
        query = query.filter(tbl.campaign_id == campaign)
    if search:
        query = query.filter(db.or_(tbl.sceneName.like(f'%{search}%')))
    total = query.count()
    order = sort_clause(tbl, sort, tblColumns, primeKey)
    query = query.order_by(*order) if order else query.order_by(tbl.sceneName)
    query = paginate(query, start, length)
    return {'data': _rows(query), 'total': total}


@router.post('/api/scenes/unlink-rule')
def unlink_rule(data: dict = Depends(json_body)):
    """Turn a smart scene back into a plain one: the rule goes, the scene and
    every song it holds stay."""
    import media.smart_scenes as smart_scenes
    from extensions import database
    try:
        sid = int(data.get('scene_ID') or 0)
    except (TypeError, ValueError):
        sid = 0
    if not sid:
        raise ApiError(400, 'scene_ID required')
    smart_scenes.drop_rule(database, sid)
    return {'ok': True}


@router.post('/api/scenes/reorder')
def reorder(data: dict = Depends(json_body)):
    """{scene_ids: [...]} in the wanted order -> orderBy 1..n (home drag & drop)."""
    ids = data.get('scene_ids')
    if not isinstance(ids, list) or not ids:
        raise ApiError(400, 'scene_ids required')
    return {'ok': True, 'updated': set_scene_order(ids)}


@router.get('/api/scenes/queue-states')
def queue_states():
    return {'ok': True, 'states': scene_queue_states()}


@router.post('/api/scenes/queue')
def queue_toggle(data: dict = Depends(json_body)):
    """{scene_ID, queued: bool} — put a scene's songs/videos into the play
    queue (or pull them out) without activating the scene."""
    try:
        scene_id = int(data.get('scene_ID') or 0)
    except (TypeError, ValueError):
        scene_id = 0
    if not scene_id:
        raise ApiError(400, 'scene_ID required')
    changed = queue_scene_songs(scene_id, bool(data.get('queued')))
    events.emit('queue', None)
    return {'ok': True, 'changed': changed, 'queued': scene_queue_state(scene_id)}


@router.post('/api/scenes')
def update(data: dict = Depends(json_body)):
    if primeKey not in data:
        raise ApiError(400, f'{primeKey} required')
    TSP = db.session.get(tbl, data[primeKey])
    if TSP is None:
        raise ApiError(404, 'scene not found')
    for field in tblColumns:
        if field in data:
            setattr(TSP, field, data[field])
    db.session.commit()
    return Response(status_code=204)


@router.post('/api/scenesaddrow')
def scenesaddrow(data: dict = Depends(json_body)):
    # The page asks whether the new scene joins the selected campaign and
    # sends campaign_id (0 = leave unassigned); bodiless calls keep the
    # historical default of campaign 1.
    row = [' ', 1, 1, int(data.get('campaign_id', 1))]
    CRUD_tblScenes(row, "C")
    return Response('tblScenes has a new row', media_type='text/plain')


@router.post('/api/scenesdelrow')
def scenesdelrow(data: dict = Depends(json_body)):
    if primeKey not in data:
        raise ApiError(400, f'{primeKey} required')
    CRUD_tblScenes([data[primeKey]], "D")
    return Response('tblScenes row ' + str(data[primeKey]) + ' has been deleted', media_type='text/plain')


@router.post('/api/sceneFilter')
def sceneFilter(data: dict = Depends(json_body)):
    scene_id = int(data['scene_id'])
    appsettingSetSceneFilter(scene_id)
    # Picking a scene drags the campaign filter along to THAT scene's campaign.
    if scene_id:
        scene = db.session.get(tbl, scene_id)
        appsettingSetCampaignFilter((scene.campaign_id or 0) if scene else 0)
    campaign = appsettingGetCampaignFilter()
    return {'campaign_id': campaign, 'scenes': [list(s) for s in scenes_for_filter(campaign)]}


@router.post('/api/campaignFilter')
def campaignFilter(data: dict = Depends(json_body)):
    """Set the global campaign filter (0=all); always RESETS the scene filter."""
    appsettingSetCampaignFilter(int(data['campaign_id']))
    appsettingSetSceneFilter(0)
    campaign = appsettingGetCampaignFilter()
    return {'campaign_id': campaign, 'scenes': [list(s) for s in scenes_for_filter(campaign)]}


# ── SPA page data ─────────────────────────────────────────────────────────────

@router.get('/api/v1/filters')
def filters():
    """The campaign/scene filter dropdowns every table page renders."""
    campaignFilter = appsettingGetCampaignFilter()
    sceneFilter = appsettingGetSceneFilter()
    return {'campaigns': [list(c) for c in campaigns_for_filter()],
            'campaignFilter': campaignFilter,
            'scenes': [list(s) for s in scenes_for_filter(campaignFilter)],
            'sceneFilter': int(sceneFilter[0][0])}


@router.get('/api/v1/home')
def home():
    """What templates/home.html rendered: campaign selector + scene cards."""
    campaigns = CRUD_tblCampaigns([], "Selected")
    campaignRow = appsettingGetCampaignSelected()
    try:
        campaignSelectedInt = int(campaignRow[0][0])
    except (IndexError, TypeError, ValueError):
        campaignSelectedInt = 0
    try:
        volume = currentvolume()
    except Exception:
        volume = 0
    return {'campaigns': [[c[0], c[1]] for c in campaigns],
            'campaign_selected': campaignSelectedInt,
            'scenes': [dict(s) for s in get_Scenes()],
            'volume': volume,
            'stats': [list(x) for x in select_data_stats()]}
