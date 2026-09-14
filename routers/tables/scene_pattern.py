"""Scene RPiLED editor (routes/scenePattern_table.py).

Rows: (scenePattern_ID, scene_ID, patternType, params JSON, orderBy).
The pattern vocabulary — which parameters each type honors, labels, ranges,
defaults — comes from led_patterns.py and is served to the page by
/api/led/patterns so the editor renders only the fields that apply.
"""
import json
import logging

from fastapi import APIRouter, Depends, Response

import core.config as config
import lighting.led_patterns as reg
from core.db import db
from models.scenePattern import tblscenepattern as tbl
from models.scenes import tblscenes as sc
from integrations.remotes import dispatch_led
from routers._util import campaign_scene_ids, json_body
from routers.tables._grid import paginate, require_pk
from security.deps import ApiError
from sql import CRUD_tblScenePattern, appsettingGetCampaignFilter, appsettingGetSceneFilter

log = logging.getLogger(__name__)

tblColumns = ['scenePattern_ID', 'scene_ID', 'patternType', 'params', 'orderBy']
primeKey = tblColumns[0]
router = APIRouter()


def _row(r):
    d = r.to_dict()
    d['name'] = reg.display_name(r.patternType)
    return d


@router.get('/api/led/patterns')
def led_registry():
    """The pattern registry for the editor: types, names, descriptions and
    the ordered field specs each one honors."""
    return reg.registry_json()


def _base_query():
    """Rows for the current scene/campaign filter. Unassigned rows (scene 0)
    are ALWAYS included: a new row starts unassigned and must stay visible
    so its scene can be picked from the grid."""
    sceneFilter = appsettingGetSceneFilter()
    campaignFilter = appsettingGetCampaignFilter()
    if int(sceneFilter[0][0]) != 0:
        return tbl.query.filter(db.or_(tbl.scene_ID == int(sceneFilter[0][0]),
                                       tbl.scene_ID == 0))
    if campaignFilter != 0:
        return tbl.query.filter(db.or_(tbl.scene_ID.in_(campaign_scene_ids(campaignFilter)),
                                       tbl.scene_ID == 0))
    return tbl.query


@router.get('/api/scenePattern')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    query = _base_query()
    if search:
        querysc = sc.query.filter(db.or_(sc.sceneName.like(f'%{search}%')))
        scene_ids = [rows.scene_ID for rows in querysc.all()]
        query = query.filter(tbl.scene_ID.in_(scene_ids))
    total = query.count()

    order = []
    if sort:
        for s in sort.split(','):
            if not s:
                continue
            direction, name = s[0], s[1:]
            if name not in tblColumns:
                name = primeKey
            col = getattr(tbl, name)
            order.append(col.desc() if direction == '-' else col)
    if not order:
        order = [tbl.scene_ID.asc(), tbl.orderBy.asc()]
    query = query.order_by(*order)
    query = paginate(query, start, length)
    return {'data': [_row(r) for r in query], 'total': total}


@router.post('/api/scenePattern')
def update(data: dict = Depends(json_body)):
    """Partial update. Changing patternType without params resets the row to
    that pattern's defaults; params are always validated against the type."""
    pk = require_pk(data, primeKey)
    row = db.session.get(tbl, int(pk))
    if row is None:
        raise ApiError(404, 'row not found')
    if 'scene_ID' in data:
        row.scene_ID = int(data['scene_ID'] or 0)
    if 'orderBy' in data:
        try:
            row.orderBy = int(data['orderBy'])
        except (TypeError, ValueError):
            pass
    if 'patternType' in data:
        ptype = str(data['patternType'] or '')
        if not reg.is_type(ptype):
            raise ApiError(400, f'unknown pattern type {ptype!r}')
        row.patternType = ptype
        row.params = json.dumps(reg.coerce(ptype, data.get('params')))
    elif 'params' in data:
        if not reg.is_type(row.patternType):
            raise ApiError(400, f'unknown pattern type {row.patternType!r}')
        row.params = json.dumps(reg.coerce(row.patternType, data['params']))
    db.session.commit()
    return Response(status_code=204)


@router.post('/api/scenepatternaddrow')
def scenesaddrow(data: dict = Depends(json_body)):
    # New rows start unassigned (scene 0) unless the caller names a scene.
    scene_id = int(data.get('scene_ID', 0) or 0)
    last = (db.session.query(db.func.max(tbl.orderBy))
            .filter(tbl.scene_ID == scene_id).scalar())
    order_by = (last or 0) + 1
    CRUD_tblScenePattern([scene_id, 'solid', json.dumps(reg.defaults('solid')),
                          order_by], "C")
    return Response('tblScenePattern has a new row', media_type='text/plain')


@router.post('/api/scenepatterndelrow')
def scenesdelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    CRUD_tblScenePattern([pk], "D")
    return Response('tblScenePattern row ' + str(pk) + ' has been deleted', media_type='text/plain')


@router.post('/api/RPiLEDTest')
def RPiLEDTest(jdata: dict = Depends(json_body)):
    """Push ONE pattern row to every LED output (this Pi, Remote boxes, the
    relay). The editor may pass unsaved patternType/params to preview them."""
    pk = require_pk(jdata, primeKey)
    row = db.session.get(tbl, int(pk))
    if row is None:
        raise ApiError(404, 'row not found')
    ptype = jdata.get('patternType') or row.patternType
    params = jdata['params'] if 'params' in jdata else row.params
    if not reg.is_type(ptype):
        raise ApiError(400, f'unknown pattern type {ptype!r}')
    payload = reg.build_payload([(ptype, params)])
    if config.INTEGRATIONS:
        dispatch_led(payload)
    else:
        log.info('RPiLEDTest suppressed (SP_INTEGRATIONS=0): %s', payload)
    return Response(status_code=204)
