"""Server-sent-events hub.

Workers are forked processes (threads on Windows) that share nothing with the
web process but the SQLite file, so the bus is a table: any process calls
emit(topic, payload) -> one INSERT; the web process tails the table and fans
rows out to per-subscriber asyncio queues. Derived topics (now-playing, queue
counts, ...) are computed by registered producers every second and emitted
only when their value changes, so code paths that never call emit() still
update the browser.
"""
import asyncio
import json
import sqlite3
import threading
import time
from datetime import datetime

import core.config as config

TOPICS = {
    'nowplaying', 'queue', 'health', 'relay', 'obs', 'downloads', 'update',
    'netscan', 'dice', 'scene', 'server', 'producer',
    # parameterised: battlemap:<id> session:<id> character:<id> syncjob:<job> aijob:<id>
}
_PARAM_PREFIXES = ('battlemap:', 'session:', 'character:', 'syncjob:', 'aijob:')

_wake = threading.Event()
_hub = None
_derived = {}          # topic -> (fn, interval_s)


def topic_ok(topic):
    return topic in TOPICS or topic.startswith(_PARAM_PREFIXES)


def ensure_table(db_path=None):
    conn = sqlite3.connect(db_path or config.DB_PATH, timeout=15)
    try:
        conn.execute('CREATE TABLE IF NOT EXISTS tblEvents ('
                     'id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, '
                     'topic TEXT NOT NULL, payload TEXT)')
        conn.commit()
    finally:
        conn.close()


_listeners = []      # in-process fn(topic, payload) callbacks (relay_producer)


def add_listener(fn):
    """Call fn(topic, payload) synchronously on every emit() in THIS process.
    For modules that must react to a topic without tailing tblEvents (the
    remote producer push). Listeners must be quick and must not raise."""
    if fn not in _listeners:
        _listeners.append(fn)


def remove_listener(fn):
    try:
        _listeners.remove(fn)
    except ValueError:
        pass


def emit(topic, payload=None):
    """Best-effort: never raises, never blocks a request or a worker."""
    for fn in list(_listeners):
        try:
            fn(topic, payload)
        except Exception:
            pass
    try:
        conn = sqlite3.connect(config.DB_PATH, timeout=15)
        try:
            conn.execute('INSERT INTO tblEvents (ts, topic, payload) VALUES (?, ?, ?)',
                         (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), topic,
                          json.dumps(payload) if payload is not None else None))
            conn.commit()
        finally:
            conn.close()
        _wake.set()
    except Exception:
        pass


def register_derived(topic, fn, interval_s=1.0):
    """fn() -> JSON-able snapshot; emitted whenever it changes."""
    _derived[topic] = (fn, float(interval_s))


def _read_since(cursor, limit=500):
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    try:
        rows = conn.execute('SELECT id, topic, payload FROM tblEvents WHERE id > ? '
                            'ORDER BY id LIMIT ?', (cursor, limit)).fetchall()
    finally:
        conn.close()
    out = []
    for rid, topic, payload in rows:
        try:
            data = json.loads(payload) if payload else None
        except ValueError:
            data = None
        out.append((rid, topic, data))
    return out


def _max_id():
    try:
        conn = sqlite3.connect(config.DB_PATH, timeout=15)
        try:
            row = conn.execute('SELECT COALESCE(MAX(id), 0) FROM tblEvents').fetchone()
        finally:
            conn.close()
        return int(row[0] or 0)
    except Exception:
        return 0


def _prune(keep=5000):
    try:
        conn = sqlite3.connect(config.DB_PATH, timeout=15)
        try:
            conn.execute('DELETE FROM tblEvents WHERE id < (SELECT COALESCE(MAX(id),0) FROM tblEvents) - ?',
                         (keep,))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


class _Sub:
    __slots__ = ('topics', 'queue')

    def __init__(self, topics):
        self.topics = set(topics)
        self.queue = asyncio.Queue(maxsize=500)

    def wants(self, topic):
        return topic in self.topics or '*' in self.topics


class EventHub:
    def __init__(self):
        self._subs = set()
        self._tasks = []
        self._cursor = 0
        self._last_values = {}
        self._snapshots = {}
        self._stop = False
        self.loop = None

    # ── subscriptions ──
    def subscribe(self, topics):
        sub = _Sub(topics)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub):
        self._subs.discard(sub)

    def snapshot(self, topic):
        return self._snapshots.get(topic)

    def replay_since(self, last_id, topics):
        try:
            return [(rid, t, d) for rid, t, d in _read_since(last_id, 2000)
                    if t in topics or '*' in topics]
        except Exception:
            return []

    def wake(self):
        _wake.set()

    # ── lifecycle ──
    async def start(self):
        global _hub
        _hub = self
        self.loop = asyncio.get_running_loop()
        ensure_table()
        self._cursor = _max_id()
        self._stop = False
        self._tasks = [asyncio.create_task(self._tail()),
                       asyncio.create_task(self._derive()),
                       asyncio.create_task(self._pruner())]

    async def stop(self):
        global _hub
        self._stop = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        if _hub is self:
            _hub = None

    # ── internals ──
    def _fanout(self, rid, topic, data):
        for sub in list(self._subs):
            if sub.wants(topic):
                try:
                    sub.queue.put_nowait((rid, topic, data))
                except asyncio.QueueFull:
                    self._subs.discard(sub)   # slow client: drop it, never block others

    async def _tail(self):
        # Always advance by READING rows (never by jumping to MAX(id)): an
        # event emitted between subscribe() and the next poll must reach the
        # new subscriber. Poll faster while anyone is listening.
        while not self._stop:
            try:
                wait_s = 0.25 if self._subs else 1.0
                woke = await asyncio.to_thread(_wake.wait, wait_s)
                if woke:
                    _wake.clear()
                rows = await asyncio.to_thread(_read_since, self._cursor)
                for rid, topic, data in rows:
                    self._cursor = rid
                    self._fanout(rid, topic, data)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)

    async def _derive(self):
        next_run = {}
        while not self._stop:
            try:
                now = time.monotonic()
                for topic, (fn, every) in list(_derived.items()):
                    if now < next_run.get(topic, 0):
                        continue
                    next_run[topic] = now + every
                    try:
                        value = await asyncio.to_thread(fn)
                    except Exception:
                        continue
                    key = json.dumps(value, sort_keys=True, default=str)
                    self._snapshots[topic] = value
                    if self._last_values.get(topic) != key:
                        self._last_values[topic] = key
                        if self._subs:
                            self._fanout(0, topic, value)
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)

    async def _pruner(self):
        while not self._stop:
            await asyncio.sleep(60)
            await asyncio.to_thread(_prune)


def hub():
    return _hub
