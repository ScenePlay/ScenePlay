"""Scene <-> WLED pattern rows + the effect/palette lookups (routes/wledPattern_table.py)."""
import logging

from fastapi import APIRouter, Depends, Response

import core.config as config
from core.db import db
from models.scenes import tblscenes as sc
from models.wledPattern import tbleffect as ef
from models.wledPattern import tblpallette as pt
from models.wledPattern import tblwledpattern as tbl
from routers._util import campaign_scene_ids, json_body
from routers.tables._grid import paginate, require_pk, sort_clause
from security.deps import ApiError
from sql import appsettingGetCampaignFilter, appsettingGetSceneFilter
from wLed.wledCommand import setWledEffect

log = logging.getLogger(__name__)

tblColumns = ['wledPattern_ID', 'scene_ID', 'server_ID', 'effect', 'pallette', 'color1', 'color2', 'color3',
              'speed', 'brightness', 'orderBy']
primeKey = tblColumns[0]
router = APIRouter()


@router.get('/api/effects')
def effect():
    return {'data': [r.to_dict() for r in ef.query.order_by(ef.effectName)]}


@router.get('/api/pallettes')
def pallette():
    return {'data': [r.to_dict() for r in pt.query.order_by(pt.palletteName)]}


@router.post('/api/WLEDTest')
def WLEDTest(jdata: dict = Depends(json_body)):
    pk = require_pk(jdata, primeKey)
    rows = getWledPatternBywledID(pk)
    for row in rows or []:
        if config.INTEGRATIONS:
            setWledEffect(row.effect, row.pallette, row.color1, row.color2, row.color3,
                          row.speed, row.brightness, row.server_ID)
        else:
            log.info('WLEDTest suppressed (SP_INTEGRATIONS=0): row %s', row.wledPattern_ID)
    return Response(status_code=204)


def _base(sceneF, campaignF, order=None):
    if sceneF != 0:
        q = tbl.query.filter(tbl.scene_ID == sceneF)
        return q.order_by(*order) if order else q.order_by(tbl.wledPattern_ID.desc())
    if campaignF != 0:
        q = tbl.query.filter(tbl.scene_ID.in_(campaign_scene_ids(campaignF)))
        return q.order_by(*order) if order else q.order_by(tbl.scene_ID)
    return tbl.query.order_by(*order) if order else tbl.query.order_by(tbl.scene_ID)


@router.get('/api/wledPattern')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    sceneF = int(appsettingGetSceneFilter()[0][0])
    campaignF = appsettingGetCampaignFilter()
    query = _base(sceneF, campaignF)
    if search:
        scene_ids = [r.scene_ID for r in sc.query.filter(db.or_(sc.sceneName.like(f'%{search}%'))).all()]
        query = tbl.query.filter(db.or_(tbl.scene_ID.in_(scene_ids)))
    total = query.count()
    order = sort_clause(tbl, sort, tblColumns, primeKey)
    if order:
        query = _base(sceneF, campaignF, order)
    query = paginate(query, start, length)
    return {'data': [r.to_dict() for r in query], 'total': total}


@router.post('/api/wledPattern')
def update(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    TSP = db.session.get(tbl, pk)
    if TSP is None:
        raise ApiError(404, 'row not found')
    for field in tblColumns:
        if field in data:
            setattr(TSP, field, data[field])
    db.session.commit()
    return Response(status_code=204)


@router.post('/api/wledpatternaddrow')
def wledaddrow(data: dict = Depends(json_body)):
    # scene_ID from the page's "join the selected scene?" prompt (0 =
    # unassigned); bodiless calls keep the old silent scene-filter stamp.
    sceneFilter = appsettingGetSceneFilter()
    newrow = tbl(scene_ID=int(data.get('scene_ID', sceneFilter[0][0])), server_ID=0, effect=0, pallette=0,
                 color1='[0,0,0]', color2='[0,0,0]', color3='[0,0,0]', speed=125, brightness=125, orderBy=1)
    db.session.add(newrow)
    db.session.commit()
    return Response('tblwledPattern has a new row', media_type='text/plain')


@router.post('/api/wledpatterndelrow')
def wleddelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    TSP = db.session.get(tbl, pk)
    if TSP is None:
        raise ApiError(404, 'row not found')
    db.session.delete(TSP)
    db.session.commit()
    return Response('tblwledPattern row ' + str(pk) + ' has been deleted', media_type='text/plain')


def getWledPatternBySceneID(sceneID):
    return tbl.query.filter(tbl.scene_ID == sceneID).all()


def getWledPatternBywledID(wledID):
    return tbl.query.filter(tbl.wledPattern_ID == wledID).all()
