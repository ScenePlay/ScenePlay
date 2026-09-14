"""RPiLED strip configuration (routes/ledconfig_table.py).

cid  name          type     notnull  dflt_value  pk
0    ledConfig_ID  INTEGER  0                    1
1    pin           INT      0                    0
2    ledCount      INT      0                    0
3    brightness    REAL     0                    0
4    active        INT      0                    0
"""
from fastapi import APIRouter, Depends, Response

from core.db import db
from models.ledConfig import tblledconfig as tbl
from routers._util import json_body
from routers.tables._grid import paginate, require_pk, sort_clause
from security.deps import ApiError

tblColumns = ['ledConfig_ID', 'pin', 'ledCount', 'brightness', 'active']
primeKey = tblColumns[0]
router = APIRouter()


@router.get('/api/ledconfigmodel')
def datalcf():
    return {'data': [r.to_dict() for r in tbl.query.order_by(tbl.pin)]}


@router.get('/api/ledconfig')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    query = tbl.query.order_by(tbl.ledConfig_ID)
    if search:
        # The Flask page searched a column this table never had (modelName);
        # match the pin / LED count text instead so the search box does something.
        query = query.filter(db.or_(db.cast(tbl.pin, db.String).like(f'%{search}%'),
                                    db.cast(tbl.ledCount, db.String).like(f'%{search}%')))
    total = query.count()
    order = sort_clause(tbl, sort, tblColumns, primeKey)
    if order:
        query = query.order_by(None).order_by(*order)   # keep the search filter (the Flask page dropped it)
    query = paginate(query, start, length)
    return {'data': [r.to_dict() for r in query], 'total': total}


@router.post('/api/ledconfigsave')
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


@router.post('/api/ledconfigdelrow')
def ledconfigdelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    row = db.session.get(tbl, pk)
    if row is None:
        raise ApiError(404, 'row not found')
    db.session.delete(row)
    db.session.commit()
    return Response('tblledconfig row ' + str(pk) + ' has been deleted', media_type='text/plain')
