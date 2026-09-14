"""Scene <-> video links (routes/videoScene_table.py)."""
from fastapi import APIRouter, Depends, Response

from core.db import db
from models.videoScene import tblvideoscene as tbl
from models.scenes import tblscenes as sc
from routers._util import campaign_scene_ids, json_body
from routers.tables._grid import apply_update, paginate, require_pk, sort_clause
from sql import CRUD_tblVideoScene, appsettingGetCampaignFilter, appsettingGetSceneFilter

tblColumns = ['videoScene_ID', 'scene_ID', 'video_ID', 'DisplayScreen_ID', 'orderBy', 'volume', 'loops']
primeKey = tblColumns[0]
router = APIRouter()


def _base(sceneF, campaignF, order=None):
    if sceneF != 0:
        q = tbl.query.filter(tbl.scene_ID == sceneF)
        return q.order_by(*order) if order else q.order_by(tbl.videoScene_ID.desc())
    if campaignF != 0:
        q = tbl.query.filter(tbl.scene_ID.in_(campaign_scene_ids(campaignF)))
        return q.order_by(*order) if order else q.order_by(tbl.scene_ID)
    return tbl.query.order_by(*order) if order else tbl.query.order_by(tbl.scene_ID)


@router.get('/api/videoScene')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    sceneF = int(appsettingGetSceneFilter()[0][0])
    campaignF = appsettingGetCampaignFilter()
    query = _base(sceneF, campaignF)
    if search:
        scene_ids = [r.scene_ID for r in sc.query.filter(db.or_(sc.sceneName.like(f'%{search}%'))).all()]
        query = query.filter(db.or_(tbl.scene_ID.in_(scene_ids))).order_by(tbl.orderBy)
    total = query.count()
    order = sort_clause(tbl, sort, tblColumns, primeKey)
    if order:
        query = _base(sceneF, campaignF, order)
    query = paginate(query, start, length)
    return {'data': [r.to_dict() for r in query], 'total': total}


@router.post('/api/videoScene')
def update(data: dict = Depends(json_body)):
    return apply_update(tbl, tblColumns, primeKey, data)


@router.post('/api/videoSceneaddrow')
def videoSceneaddrow(data: dict = Depends(json_body)):
    sceneFilter = appsettingGetSceneFilter()
    row = [int(data.get('scene_ID', sceneFilter[0][0])), 0, 0, 1, 100, 0]
    CRUD_tblVideoScene(row, "C")
    return Response('tblvideoScene has a new row', media_type='text/plain')


@router.post('/api/videoScenedelrow')
def videoScenedelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    CRUD_tblVideoScene([pk], "D")
    return Response('tblvideoScene row ' + str(pk) + ' has been deleted', media_type='text/plain')
