"""Server roles (routes/serverRole_table.py)."""
from fastapi import APIRouter, Depends, Response

from core.db import db
from models.serverRole import tblserverrole as tbl
from routers._util import json_body
from routers.tables._grid import paginate, require_pk, sort_clause
from security.deps import ApiError
from sql import CRUD_tblServerRole

tblColumns = ['ID', 'name', 'active', 'orderBy']
primeKey = tblColumns[0]
router = APIRouter()


@router.get('/api/serverrole')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    query = tbl.query.order_by(tbl.name)
    if search:
        query = query.filter(db.or_(tbl.name.like(f'%{search}%')))
    total = query.count()
    order = sort_clause(tbl, sort, tblColumns, primeKey)
    if order:
        query = query.order_by(*order)
    query = paginate(query, start, length)
    return {'data': [r.to_dict() for r in query], 'total': total}


@router.post('/api/serverrole')
def update(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    TSP = db.session.get(tbl, pk)
    if TSP is None:
        raise ApiError(404, 'row not found')
    if 'name' in data:
        TSP.name = data['name']
    db.session.commit()
    return Response(status_code=204)


@router.api_route('/api/serverroleaddrow', methods=['GET', 'POST'])
def serverroleaddrow():
    CRUD_tblServerRole(['new', 1, 1], "C")
    return Response('tblserverrole has a new row', media_type='text/plain')


@router.post('/api/serverroledelrow')
def serverroledelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    CRUD_tblServerRole([pk], "D")
    return Response('tblserverrole row ' + str(pk) + ' has been deleted', media_type='text/plain')
