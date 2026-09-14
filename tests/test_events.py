"""Event hub: emit() from another process is seen by the hub, topic filter,
unknown topics rejected, SSE requires a user, prune keeps the tail."""
import multiprocessing
import sqlite3
import time

import core.config as config
import core.events as events


def _child_emit(db_path):
    import os
    os.environ['SP_DB_PATH'] = db_path
    import importlib
    import core.config as c
    importlib.reload(c)
    import core.events as e
    e.emit('dice', {'from': 'child', 'total': 9})


def test_emit_writes_row_and_child_process_emit_visible(client):
    before = events._max_id()
    events.emit('dice', {'total': 3})
    assert events._max_id() == before + 1
    p = multiprocessing.get_context('spawn').Process(target=_child_emit, args=(config.DB_PATH,))
    p.start(); p.join(30)
    rows = events._read_since(before)
    assert [r[1] for r in rows] == ['dice', 'dice']
    assert rows[-1][2] == {'from': 'child', 'total': 9}


def test_unknown_topic_rejected(client, dm_token):
    r = client.get('/api/v1/events?topics=bogus', headers={'Authorization': f'Bearer {dm_token}'})
    assert r.status_code == 400
    r = client.get('/api/v1/events?topics=dice')
    assert r.status_code == 401


def test_topic_ok():
    assert events.topic_ok('battlemap:12') and events.topic_ok('syncjob:spells')
    assert not events.topic_ok('battlemap') and not events.topic_ok('x')


def test_prune_keeps_tail(client):
    for i in range(20):
        events.emit('server', {'i': i})
    events._prune(keep=5)
    conn = sqlite3.connect(config.DB_PATH)
    n = conn.execute('SELECT COUNT(*) FROM tblEvents').fetchone()[0]
    conn.close()
    assert n <= 6


def test_hub_fanout_and_slow_client_drop(client):
    import asyncio
    hub = client.app.state.hub
    sub = hub.subscribe({'dice'})
    other = hub.subscribe({'nowplaying'})
    events.emit('dice', {'total': 11})
    deadline = time.time() + 5
    got = None
    while time.time() < deadline and got is None:
        try:
            got = sub.queue.get_nowait()
        except asyncio.QueueEmpty:
            time.sleep(0.1)
    assert got and got[1] == 'dice' and got[2] == {'total': 11}
    assert other.queue.empty()
    hub.unsubscribe(sub); hub.unsubscribe(other)
    # a subscriber whose queue is full is dropped instead of blocking others
    slow = hub.subscribe({'dice'})
    for _ in range(600):
        try:
            slow.queue.put_nowait((0, 'dice', None))
        except asyncio.QueueFull:
            break
    hub._fanout(0, 'dice', {'x': 1})
    assert slow not in hub._subs


def test_producer_topic_is_accepted(client, dm_token):
    assert events.topic_ok('producer')
    with client.stream('GET', '/api/v1/events?topics=producer',
                       headers={'Authorization': f'Bearer {dm_token}'}) as r:
        assert r.status_code == 200
        first = next(r.iter_lines())
        assert 'hello' in first
