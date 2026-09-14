"""Campaigns table (routes/campaign_table.py)."""
from fastapi import APIRouter, Depends, Response

from core.db import db
from models.campaigns import tblcampaigns as tbl
from routers._util import json_body
from routers.tables._grid import apply_update, paginate, require_pk, sort_clause
from security.deps import ApiError
from sql import appsettingGetCampaignSelected, appsettingSet, appsettingSetCampaignSelected
import core.events as events

tblColumns = ['campaign_id', 'campaign_name', 'active', 'order_by']
primeKey = tblColumns[0]
router = APIRouter()


@router.get('/api/campaigns')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    query = tbl.query.order_by(tbl.campaign_name)
    if search:
        query = query.filter(db.or_(tbl.campaign_name.like(f'%{search}%')))
    total = query.count()
    order = sort_clause(tbl, sort, tblColumns, primeKey)
    if order:
        query = tbl.query.order_by(*order)
    query = paginate(query, start, length)
    return {'data': [r.to_dict() for r in query], 'total': total}


@router.post('/api/campaigns')
def update(data: dict = Depends(json_body)):
    return apply_update(tbl, tblColumns, primeKey, data)


@router.post('/api/campaignaddrow')
def campaignaddrow():
    newrow = tbl(campaign_name=' ', active=1, order_by='10')
    db.session.add(newrow)
    db.session.commit()
    return Response('tblCampaign has a new row', media_type='text/plain')


@router.post('/api/campaigndelrow')
def campaigndelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    TSP = db.session.get(tbl, pk)
    if TSP is None:
        raise ApiError(404, 'campaign not found')
    db.session.delete(TSP)
    db.session.commit()
    return Response('tblCampaign row ' + str(pk) + ' has been deleted', media_type='text/plain')


@router.post('/api/campaignSelect')
def updateCampaignSelect(data: dict = Depends(json_body)):
    appsettingSetCampaignSelected(int(data['campaign_id']))
    # Fresh campaign = fresh slate: clear the failure alerts (navbar badges).
    appsettingSet('remote_send_last_fail', '')
    appsettingSet('relay_push_last_drop', '')
    appsettingSet('wled_send_last_fail', '')
    events.emit('health', None)
    return Response(status_code=204)


@router.post('/api/alertsClear')
def alerts_clear():
    appsettingSet('remote_send_last_fail', '')
    appsettingSet('relay_push_last_drop', '')
    appsettingSet('wled_send_last_fail', '')
    events.emit('health', None)
    return Response(status_code=204)


@router.get('/api/getcampaignSelect')
def updateGetCampaignSelect():
    data = appsettingGetCampaignSelected()
    return {'CampaignID': int(data[0][0])}
