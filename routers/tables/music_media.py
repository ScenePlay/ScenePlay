"""Music media table (routes/musicMedia_table.py)."""
from fastapi import APIRouter, Depends, Response

from core.db import db
from models.mediaMetadata import tblmediametadata as metaTbl
from models.music import tblmusic as tbl
from models.musicScene import tblmusicscene as sceneLinkTbl
from routers._util import json_body
from routers.tables._grid import require_pk
from routers.tables._media import list_media
from security.deps import ApiError
from sql import (CRUD_tblMusic, CRUD_tblMusicScene, appsettingAudioPlayFlagUpdate,
                 appsettingYT_QuePlayFlagUpdate, delete_media_row, requeue_metadata_if_missing)
import core.events as events

tblColumns = ['song_ID', 'path', 'song', 'pTimes', 'playedDTTM', 'active', 'genre', 'que', 'urlSource',
              'dnLoadStatus', 'videoId', 'displayName', 'metaStatus']
primeKey = tblColumns[0]
_meta_sort = {'duration': metaTbl.duration, 'uploader': metaTbl.uploader, 'artist': metaTbl.artist}
router = APIRouter()


@router.get('/api/music')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    def _artist(d, m):
        d['artist'] = (m.artist or '') if m else ''
    return list_media(tbl, 'music', tbl.song_id, [tbl.song, tbl.displayName], sceneLinkTbl,
                      sceneLinkTbl.song_ID, tblColumns, primeKey, _meta_sort, search, sort, start, length,
                      extra_row=_artist)


@router.post('/api/music')
def update(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    TSP = db.session.get(tbl, pk)
    if TSP is None:
        raise ApiError(404, 'row not found')
    # videoId / metaStatus are machine-managed; artist lives on the metadata row.
    if 'artist' in data:
        import media.media_facets as media_facets
        from extensions import database
        media_facets.apply_artists(database, [{'media_type': 'music', 'id': pk, 'artist': data['artist']}])
    for field in tblColumns:
        if field in ('videoId', 'metaStatus', 'artist') or field not in data:
            continue
        setattr(TSP, field, data[field])
        if field == 'dnLoadStatus' and int(data['dnLoadStatus']) == 1:
            appsettingYT_QuePlayFlagUpdate(1)
            requeue_metadata_if_missing('music', pk)
            events.emit('downloads', None)
        if field == 'que' and int(data['que']) == 1:
            appsettingAudioPlayFlagUpdate(1)
    db.session.commit()
    return Response(status_code=204)


@router.post('/api/musicaddrow')
def musicaddrow(data: dict = Depends(json_body)):
    row = [' ', ' ', 0, '', 1, 1, 0, '', '']
    media_id = CRUD_tblMusic(row, "C")
    scene_id = int(data.get('scene_ID', 0))
    if scene_id:
        CRUD_tblMusicScene([scene_id, media_id, 1, 100], "C")
    return Response('tblmusic has a new row', media_type='text/plain')


@router.post('/api/musicdelrow')
def musicdelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    links = delete_media_row('music', pk)
    return {'deleted': pk, 'scene_links_removed': links}
