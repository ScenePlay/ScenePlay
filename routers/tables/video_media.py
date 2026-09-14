"""Video media table (routes/videoMedia_table.py)."""
from fastapi import APIRouter, Depends, Response

from core.db import db
from models.mediaMetadata import tblmediametadata as metaTbl
from models.videoMedia import tblvideomedia as tbl
from models.videoScene import tblvideoscene as sceneLinkTbl
from routers._util import json_body
from routers.tables._grid import require_pk
from routers.tables._media import list_media
from security.deps import ApiError
from sql import (CRUD_tblVideoScene, CRUD_tblvideomedia, appsettingVideoPlayFlagUpdate,
                 appsettingYT_QuePlayFlagUpdate, delete_media_row, requeue_metadata_if_missing)
import core.events as events

tblColumns = ['video_ID', 'path', 'title', 'pTimes', 'playedDTTM', 'active', 'genre', 'que', 'urlSource',
              'dnLoadStatus', 'videoId', 'displayName', 'metaStatus']
primeKey = tblColumns[0]
_meta_sort = {'duration': metaTbl.duration, 'uploader': metaTbl.uploader}
router = APIRouter()


@router.get('/api/videomedia')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    return list_media(tbl, 'video', tbl.video_id, [tbl.title, tbl.displayName], sceneLinkTbl,
                      sceneLinkTbl.video_ID, tblColumns, primeKey, _meta_sort, search, sort, start, length)


@router.post('/api/videomedia')
def update(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    TSP = db.session.get(tbl, pk)
    if TSP is None:
        raise ApiError(404, 'row not found')
    for field in tblColumns:
        if field in ('videoId', 'metaStatus') or field not in data:
            continue
        setattr(TSP, field, data[field])
        if field == 'dnLoadStatus' and int(data['dnLoadStatus']) == 1:
            appsettingYT_QuePlayFlagUpdate(1)
            requeue_metadata_if_missing('video', pk)
            events.emit('downloads', None)
        if field == 'que' and int(data['que']) == 1:
            appsettingVideoPlayFlagUpdate(1)
    db.session.commit()
    return Response(status_code=204)


@router.post('/api/videomediaaddrow')
def videomediaaddrow(data: dict = Depends(json_body)):
    row = ['empty', 'empty', 0, '', 1, 1, 0, '', '']
    media_id = CRUD_tblvideomedia(row, "C")
    scene_id = int(data.get('scene_ID', 0))
    if scene_id:
        CRUD_tblVideoScene([scene_id, media_id, 0, 1, 100, 0], "C")
    return Response('tblvideomedia has a new row', media_type='text/plain')


@router.post('/api/videomediadelrow')
def videomediadelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    links = delete_media_row('video', pk)
    return {'deleted': pk, 'scene_links_removed': links}
