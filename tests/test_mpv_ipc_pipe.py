"""The Windows named-pipe transport behind media.mpv_ipc.

Windows only (a \\\\.\\pipe\\ server has no Linux stand-in). The persistent
music player keeps a reader thread parked in read_line() the whole session;
the player thread must still be able to write the next command while that
read is pending. The first port opened the pipe as a Python file object,
where a blocking read holds the C runtime's descriptor lock, so the write
waited on mpv — which, idle, never spoke. No track ever loaded.
"""
import os
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows named-pipe transport')


@pytest.fixture()
def pipe_server():
    """A message pipe server that replies to the first line it receives after
    a pause, so the client's read is genuinely pending when the write goes out."""
    from multiprocessing.connection import Listener
    name = r'\\.\pipe\sp-test-mpv-%d-%d' % (os.getpid(), int(time.time() * 1000))
    listener = Listener(name, family='AF_PIPE')
    received = []
    replies = [b'{"request_id":1,"error":"success","data":true}\n']

    def serve():
        conn = listener.accept()
        try:
            received.append(conn.recv_bytes())
            time.sleep(0.3)
            for r in replies:
                conn.send_bytes(r)
            time.sleep(0.3)
        finally:
            conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield name, received, replies
    listener.close()
    t.join(3)


def test_a_pending_read_does_not_block_the_next_write(pipe_server):
    from media.mpv_ipc import _Transport
    name, received, _ = pipe_server
    tr = _Transport(name, timeout=2.0)
    lines = []

    def reader():
        while True:
            try:
                line = tr.read_line(timeout=0.5)
            except ConnectionError:
                return
            if line:
                lines.append(line)
                return
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    time.sleep(0.2)                       # the reader is parked in its pending read
    t0 = time.monotonic()
    tr.write_line('{"command":["get_property","idle-active"],"request_id":1}')
    assert time.monotonic() - t0 < 1.0    # the file-object transport never returned here
    t.join(3)
    assert received == [b'{"command":["get_property","idle-active"],"request_id":1}\n']
    assert lines == ['{"request_id":1,"error":"success","data":true}']
    tr.close()


def test_read_times_out_quietly_and_reports_a_closed_pipe(pipe_server):
    from media.mpv_ipc import _Transport
    name, _, _ = pipe_server
    tr = _Transport(name, timeout=2.0)
    t0 = time.monotonic()
    assert tr.read_line(timeout=0.2) is None          # nothing sent yet: a timeout, not an error
    assert 0.1 < time.monotonic() - t0 < 1.5
    tr.write_line('{"command":["get_property","idle-active"],"request_id":1}')
    assert tr.read_line(timeout=3.0) == '{"request_id":1,"error":"success","data":true}'
    time.sleep(0.6)                                    # the server hangs up after its reply
    with pytest.raises(ConnectionError):
        for _ in range(10):
            if tr.read_line(timeout=0.5) is None:
                continue
    tr.close()


def test_client_round_trip_over_the_pipe(pipe_server):
    from media.mpv_ipc import MpvClient
    name, _, _ = pipe_server
    c = MpvClient(name).connect(timeout=3)
    try:
        assert c.command('get_property', 'idle-active') is True
    finally:
        c.close()
