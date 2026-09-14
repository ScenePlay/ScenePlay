"""Shared listing logic for the music and video media tables."""
from core.db import db
from models.mediaMetadata import tblmediametadata as metaTbl
from routers._util import campaign_scene_ids
from routers.tables._grid import paginate, sort_clause
from sql import appsettingGetCampaignFilter, appsettingGetSceneFilter
from media.thumbs import store as thumb_store


def list_media(tbl, media_type, pk_col, name_cols, link_tbl, link_media_col, columns, prime_key,
               meta_sort, search, sort, start, length, extra_row=None):
    query = tbl.query
    sceneFilter = int(appsettingGetSceneFilter()[0][0])
    campaignFilter = appsettingGetCampaignFilter()
    if sceneFilter != 0:
        ids = db.session.query(link_media_col).filter(link_tbl.scene_ID == sceneFilter)
        query = query.filter(pk_col.in_(ids))
    elif campaignFilter != 0:
        ids = db.session.query(link_media_col).filter(link_tbl.scene_ID.in_(campaign_scene_ids(campaignFilter)))
        query = query.filter(pk_col.in_(ids))
    if search:
        query = query.filter(db.or_(*[c.like(f'%{search}%') for c in name_cols]))
    total = query.count()
    order = []
    if sort:
        joined = False
        for s in sort.split(','):
            if not s:
                continue
            direction, name = s[0], s[1:]
            if name in meta_sort:
                if not joined:
                    query = query.outerjoin(metaTbl, db.and_(metaTbl.media_type == media_type,
                                                              metaTbl.media_id == pk_col))
                    joined = True
                col = meta_sort[name]
            else:
                col = getattr(tbl, name if name in columns else prime_key, None)
                if col is None:
                    col = pk_col
            order.append(col.desc() if direction == '-' else col)
    name_key = db.func.coalesce(db.func.nullif(tbl.displayName, ''), name_cols[0])
    query = query.order_by(*order) if order else query.order_by(name_key)
    query = paginate(query, start, length)
    rows = query.all()
    ids = [getattr(r, pk_col.key) for r in rows]
    meta = {m.media_id: m for m in metaTbl.query.filter(
        metaTbl.media_type == media_type, metaTbl.media_id.in_(ids))} if ids else {}
    data = []
    for r in rows:
        d = r.to_dict()
        rid = getattr(r, pk_col.key)
        m = meta.get(rid)
        d['duration'] = m.duration if m else None
        d['uploader'] = m.uploader if m else None
        if extra_row:
            extra_row(d, m)
        d['thumbnail'] = thumb_store.url(media_type, rid) or (m.thumbnail if m else None)
        data.append(d)
    return {'data': data, 'total': total}
