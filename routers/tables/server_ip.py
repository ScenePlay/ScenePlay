"""Servers table + the LAN scan (routes/serverIP_table.py).

cid  name          type     notnull  dflt_value  pk
0    ServerIP_ID   INTEGER  0                    1
1    serverName    TEXT     0                    0
2    ipAddress     TEXT     0                    0
3    ports         TEXT     0                    0
4    active        INT      0                    0
5    PingTime      TEXT     0                    0
6    serverroleid  INT      0                    0

The scan runs on a discovery.py daemon thread; its progress dict is pushed to
the page over SSE (`netscan`) by a watcher thread here — the old page polled
GET /api/pingnetwork/status every 500 ms, which stays as the fallback.
"""
import threading
import time

from fastapi import APIRouter, Depends, Response

import integrations.discovery as discovery
import core.events as events
from core.appctx import ctx as appctx
from core.db import db
from models.serverIP import tblserversip as tbl
from routers._util import json_body
from routers.tables._grid import paginate, require_pk, sort_clause
from security.deps import ApiError
from sql import CRUD_tblServersIP

tblColumns = ['ServerIP_ID', 'serverName', 'version', 'ipAddress', 'ports', 'active', 'PingTime', 'serverroleid']
primeKey = tblColumns[0]
router = APIRouter()

_RUNNING = ('sweeping', 'identifying')
_EMIT_EVERY_S = 0.5
_watch_lock = threading.Lock()
_watching = False


def _watch_scan():
    """Emit `netscan` while the scan runs (twice a second, like the old poll)
    and once more with the final state."""
    global _watching
    last = None
    try:
        deadline = time.time() + 600
        while time.time() < deadline:
            p = discovery.get_progress()
            if p != last:
                events.emit('netscan', p)
                last = p
            if p.get('state') not in _RUNNING:
                break
            time.sleep(_EMIT_EVERY_S)
    finally:
        with _watch_lock:
            _watching = False


def _start_watcher():
    global _watching
    with _watch_lock:
        if _watching:
            return
        _watching = True
    threading.Thread(target=_watch_scan, daemon=True, name='netscan-watch').start()


@router.post('/api/pingnetwork')
def pingnetwork_start():
    """Kick off the background LAN scan (discovery.py). started=False means a
    scan is already running — the status endpoint will show its progress."""
    started = discovery.start_scan(appctx)
    _start_watcher()
    return {'started': started}


@router.get('/api/pingnetwork/status')
def pingnetwork_status():
    """Scan progress for the status bar: state (idle/sweeping/identifying/
    done/error), done/total counters, and the result summary when finished."""
    return discovery.get_progress()


@router.get('/api/serverIP')
def data(search: str = None, sort: str = None, start: int = -1, length: int = -1):
    query = tbl.query.order_by(tbl.serverName)
    if search:
        query = query.filter(db.or_(
            tbl.serverName.like(f'%{search}%'),
            tbl.ports.like(f'%{search}%'),
            tbl.ipAddress.like(f'%{search}%'),
        ))
    total = query.count()
    order = sort_clause(tbl, sort, tblColumns, primeKey)
    if order:
        query = query.order_by(None).order_by(*order)   # keep the search filter (the Flask page dropped it)
    query = paginate(query, start, length)
    return {'data': [r.to_dict() for r in query], 'total': total}


@router.post('/api/serverIP')
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


@router.post('/api/serveripaddrow')
def scenesaddrow():
    CRUD_tblServersIP([' ', '127.0.0.1', '', 1, 1], "C")
    return Response('tblserverip has a new row', media_type='text/plain')


@router.post('/api/serveripdelrow')
def scenesdelrow(data: dict = Depends(json_body)):
    pk = require_pk(data, primeKey)
    CRUD_tblServersIP([pk], "D")
    return Response('tblserverip row ' + str(pk) + ' has been deleted', media_type='text/plain')
