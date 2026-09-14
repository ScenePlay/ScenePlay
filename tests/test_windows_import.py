"""Windows parity of the boot path: with os.name == 'nt' the six workers start
as daemon threads (never a fork), the duplicate-instance probe skips
SO_REUSEADDR, and the boot modules import without any Linux-only module
at import time (fcntl / pulsectl / SIGCHLD wiring is runtime-guarded)."""
import importlib
import os
import subprocess
import sys

import pytest


def test_boot_modules_import_without_linux_only_modules():
    """Simulate the Windows import environment in a subprocess: block fcntl,
    pulsectl and python-crontab, stub pycaw/comtypes, set os.name = 'nt', and
    import the modules ws.py needs at boot."""
    code = r'''
import os, sys, types
# third-party stacks import first (they are the same on Windows); the block
# below is about OUR modules' import-time behaviour
import sqlalchemy, fastapi, starlette, alembic, jwt, bcrypt, requests, PIL, psutil  # noqa
blocked = {'fcntl', 'pulsectl', 'crontab'}
class _Block:
    def find_spec(self, name, path=None, target=None):
        if name in blocked:
            raise ImportError(f'{name} is not available on Windows')
        return None
sys.meta_path.insert(0, _Block())
for m in ('pycaw', 'pycaw.pycaw', 'comtypes'):
    sys.modules[m] = types.ModuleType(m)
sys.modules['pycaw.pycaw'].AudioUtilities = object
sys.modules['pycaw.pycaw'].IAudioEndpointVolume = object
sys.modules['comtypes'].CLSCTX_ALL = 0
sys.modules['comtypes'].cast = lambda *a, **k: None
sys.modules['comtypes'].POINTER = lambda x: x
sys.modules['comtypes'].CoInitialize = lambda: None
sys.modules['comtypes'].CoUninitialize = lambda: None
import pathlib
# os.name='nt' makes Path() pick WindowsPath; keep paths usable on this box
for _m in (pathlib, getattr(pathlib, '_local', None)):
    if _m is not None and hasattr(_m, 'WindowsPath'):
        _m.WindowsPath = pathlib.PosixPath
os.name = 'nt'
os.environ.update(SP_WORKERS='0', SP_INTEGRATIONS='0', SP_DB_PATH=os.path.join(os.environ['TMPDIR_T'], 'w.db'))
import core.config, core.boot, extensions, core.db, core.db_migrate, security.deps, core.urls  # noqa
print('imported', os.name)
'''
    env = dict(os.environ, TMPDIR_T=os.environ.get('TMPDIR', '/tmp'), PYTHONPATH=os.getcwd())
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, cwd=os.getcwd(), timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert 'imported nt' in r.stdout


def test_workers_are_threads_on_windows(monkeypatch, app):
    import core.boot as boot
    import threading
    import multiprocessing
    started = []

    class FakeThread:
        def __init__(self, target=None, args=(), daemon=None, name=''):
            started.append(('thread', name, daemon))

        def start(self):
            pass

    def no_fork(*a, **k):
        raise AssertionError('fork context must not be used on Windows')

    # the worker modules import lazily inside start_workers — warm them up while os.name is still posix
    import media.player, media.mpvPlayer, media.yt_que, media.meta_que, media.playlist_que, ops.backup_restore  # noqa: F401
    monkeypatch.setattr(os, 'name', 'nt')
    monkeypatch.setattr(threading, 'Thread', FakeThread)
    monkeypatch.setattr(multiprocessing, 'get_context', no_fork)
    monkeypatch.setattr(boot, 'seed_appsettings', lambda: None)
    import sql
    for fn in ('appsettingAudioPlayFlagUpdate', 'appsettingVideoPlayFlagUpdate', 'appsettingYT_QuePlayFlagUpdate',
               'recover_stuck_processing'):
        monkeypatch.setattr(sql, fn, lambda *a, **k: None)
    boot.start_workers()
    names = [n for kind, n, d in started]
    assert all(kind == 'thread' and d is True for kind, _n, d in started)
    assert any('threaderVideo' in n for n in names) and any('YTQue_threader' in n for n in names)
    assert len(started) >= 4


def test_instance_probe_skips_reuseaddr_on_windows(monkeypatch):
    import core.boot as boot
    import socket
    calls = []

    class FakeSock:
        def setsockopt(self, *a):
            calls.append(a)

        def bind(self, addr):
            pass

        def close(self):
            pass

    monkeypatch.setattr(os, 'name', 'nt')
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: FakeSock())
    assert boot.another_instance_running(65001) is False
    assert calls == []


def test_config_port_and_socket_prefix_from_env(monkeypatch):
    """Everything that bakes the port derives from SP_PORT (scene_end, discovery, remotes)."""
    import core.config as config
    import media.scene_end as scene_end
    import integrations.discovery as discovery
    import integrations.remotes as remotes
    assert config.PORT == int(os.environ.get('SP_PORT', '8086'))
    for mod, attr in ((scene_end, 'APP_PORT'), (discovery, 'SCENEPLAY_PORT'), (remotes, 'REMOTE_PORT')):
        if hasattr(mod, attr):
            assert int(getattr(mod, attr)) == config.PORT, attr
    importlib.reload(config)
    assert config.MPV_SOCKET_PREFIX
