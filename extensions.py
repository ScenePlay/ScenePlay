"""Flask-free replacement for the old extensions module.

Keeps the names the legacy star-import chains rely on (`database`,
`databaseDir`, `db`, `bcrypt`, `getmixer`, `currentvolume`, `setvolume`) so
sql.py, the models, the workers and backup_restore.py import unchanged.
"""
import os

import core.config as config

# Master-volume backend is OS-specific: PulseAudio on Linux, Windows Core
# Audio (pycaw) on Windows. Linux-only libraries are excluded behind the
# os.name check so the app can import on Windows.
if os.name != 'nt':
    import pulsectl

database = config.DB_PATH      # full path (the Flask version relied on cwd == repo root)
databaseDir = config.DB_PATH

from core.db import db                       # noqa: E402  (SQLAlchemy shim)
from security.passwords import bcrypt   # noqa: E402  (Flask-Bcrypt-compatible)


# --- Windows master volume: single-threaded COM worker -----------------------
# COM objects (pycaw/comtypes) are NOT safe to create in one thread and release
# in another: with the server serving from a threadpool, endpoint objects made
# per-request got garbage-collected on other threads, and the cross-thread
# Release is an access violation in _ctypes.pyd that kills the whole process.
# So ONE daemon thread owns COM for its whole life; request threads only pass
# messages to it and never touch a COM object.
if os.name == 'nt':
    import threading
    import queue as _queue

    _audio_requests = _queue.Queue()
    _audio_thread = None
    _audio_thread_lock = threading.Lock()

    def _audio_worker():
        import comtypes
        import gc
        from ctypes import POINTER, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        comtypes.CoInitialize()
        while True:
            op, val, reply = _audio_requests.get()
            result = None
            try:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
                endpoint = cast(interface, POINTER(IAudioEndpointVolume))
                if op == 'get':
                    result = round(endpoint.GetMasterVolumeLevelScalar() * 100)
                else:
                    endpoint.SetMasterVolumeLevelScalar(max(0, min(100, int(val))) / 100, None)
                del endpoint, interface, devices
            except Exception:
                result = None
            # comtypes leaves a POINTER(IUnknown) in a reference cycle; collect
            # HERE so its finalizer runs on the COM thread.
            try:
                gc.collect()
            except Exception:
                pass
            if reply is not None:
                reply.put(result)

    def _audio_request(op, val=None, timeout=3.0):
        """Send one get/set to the COM thread; None on failure/timeout."""
        global _audio_thread
        with _audio_thread_lock:
            if _audio_thread is None or not _audio_thread.is_alive():
                _audio_thread = threading.Thread(target=_audio_worker, daemon=True,
                                                 name='audio-com-worker')
                _audio_thread.start()
        reply = _queue.Queue(1)
        _audio_requests.put((op, val, reply))
        try:
            return reply.get(timeout=timeout)
        except _queue.Empty:
            return None


def getmixer():
    if os.name == 'nt':
        return []   # sinks are a PulseAudio concept; setvolume handles nt directly

    with pulsectl.Pulse('volume-control') as pulse:
        mixers = pulse.sink_list()
    return mixers


def currentvolume():
    if os.name == 'nt':
        vol = _audio_request('get')
        return vol if vol is not None else 0

    with pulsectl.Pulse('volume-getter') as pulse:
        server_info = pulse.server_info()
        default_sink_name = server_info.default_sink_name
        sink = pulse.get_sink_by_name(default_sink_name)
    volume = round(sink.volume.value_flat * 100)
    return volume


def setvolume(volume):
    if os.name == 'nt':
        _audio_request('set', volume)
        return

    with pulsectl.Pulse('volume-control') as pulse:
        mixers = getmixer()
        for sink in mixers:
            pulse.volume_set_all_chans(sink, volume / 100)
    return
