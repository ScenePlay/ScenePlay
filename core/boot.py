"""Boot helpers shared by ws.py: SIGCHLD reaper, duplicate-instance probe,
dependency check, the worker start (ported from app.py startTheadPlayer) and
the relay/OBS bring-up (ported from the same, guarded against boot loops)."""
import os
import signal
import socket
import sys
import time

import core.config as config


def reap_child(signum, frame):
    """Reap exited children so they never linger as zombies — and do NOTHING
    else (a reaped pid is free for kernel reuse the instant waitpid returns)."""
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
        except ChildProcessError:
            break


def install_reaper():
    if hasattr(signal, 'SIGCHLD'):
        signal.signal(signal.SIGCHLD, reap_child)


def another_instance_running(port=None):
    """True when the app already runs elsewhere. Starting anyway would add a
    second set of queue workers racing for the same DB rows."""
    port = port or config.PORT
    probe = socket.socket()
    if os.name != 'nt':
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind(('0.0.0.0', port))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def refuse_if_running(port=None):
    if another_instance_running(port):
        print(f'*** ScenePlay is already running (port {port or config.PORT} in use) — '
              'not starting a second instance. ***\n'
              '    Debugging? Stop the other copy first, then start again.',
              file=sys.stderr, flush=True)
        sys.exit(1)


def warn_missing_tools():
    import shutil
    for _tool, _why in (('mpv', 'music/video playback'),
                        ('ffmpeg', 'yt-dlp audio extract / video merge')):
        if not shutil.which(_tool):
            print(f'*** WARNING: {_tool!r} not found on PATH — {_why} will fail. ***')


def ensure_upload_dirs():
    for _upload_dir in ('battlemaps', 'portraits', 'weapons', 'armor', 'monsters', 'textures',
                        'handouts', 'obs'):
        os.makedirs(os.path.join(config.UPLOADS_DIR, _upload_dir), exist_ok=True)


def apparray():
    from sql import CRUD_tblAppSettings
    watch = 1
    for a in CRUD_tblAppSettings([], ""):
        if a[1] == "WatchManage":
            watch = int(a[2])
            break
    return [
        ["ospid", os.getpid(), "int"],
        ["volume", 0, "int"],
        ["currentsong", "0", "text"],
        ["currentvideo", "0", "text"],
        ["playsongswitch", 1, "int"],
        ["playsongPID", 1, "int"],
        ["playvideoswitch", 1, "int"],
        ["playvideoPID", 1, "int"],
        ["yt_que_switch", 1, "int"],
        ["yt_que_PID", 1, "int"],
        ["WatchManage", watch, "int"],
        ["ShowCampaign", 0, "int"],
        ["CurrentCampaignPlaying", 0, "int"],
        ["SceneFilter", 0, "int"],
        ["Empty2", 0, "int"],
        ["meta_que_switch", 1, "int"],
        ["playlist_que_switch", 1, "int"],
        ["CurrentScene", 0, "int"],
        ["dl_sound_ok", 1, "int"],
        ["dl_sound_fail", 1, "int"],
    ]


def seed_appsettings():
    from sql import appsettings
    appsettings(apparray())


def _die_with_parent():
    """Linux: ask the kernel to SIGTERM this worker when the web process
    exits, so a killed ws.py never leaves pollers (or their mpv) behind.
    No-op elsewhere (Windows workers are daemon threads)."""
    if os.name == 'nt':
        return
    try:
        import ctypes
        import signal
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except Exception:
        pass


def start_workers():
    """Six sqlite pollers: forked Processes on Linux (explicit fork context —
    3.14's forkserver can't pickle the closures), daemon threads on Windows.
    MUST run before uvicorn builds its event loop: forking after that
    inherits loop fds, signal handlers and pool threads."""
    import multiprocessing
    import threading
    from multiprocessing import Array, Value
    from sql import (appsettingAudioPlayFlagUpdate, appsettingAudioPlayFlagUpdatePID,
                     appsettingFlagUpdate, appsettingVideoPlayFlagUpdate,
                     appsettingYT_QuePlayFlagUpdate, appsettingYT_QuePlayFlagUpdatePID,
                     queue_next, recover_stuck_processing)
    if config.PLAYER == 'ipc':
        from media.player_ipc import threader          # persistent mpv over JSON IPC
    else:
        from media.player import threader              # classic: one mpv per track
    from media.mpvPlayer import threaderVideo
    from media.yt_que import YTQue_threader
    from media.meta_que import MetaQue_threader
    from media.playlist_que import PlaylistQue_threader
    from ops.backup_restore import Backup_threader

    if os.name != 'nt' and threading.active_count() != 1:
        print(f'*** WARNING: forking workers with {threading.active_count()} threads alive ***')

    seed_appsettings()
    appsettingAudioPlayFlagUpdate(0)
    appsettingVideoPlayFlagUpdate(0)
    appsettingYT_QuePlayFlagUpdate(0)

    num = Value('i', 1)
    arr = Array('i', range(15))
    arr[0] = os.getpid()

    def start_worker(target, args=()):
        def _guarded(*a):
            _die_with_parent()
            try:
                target(*a)
            except Exception:
                import traceback
                try:
                    with open(os.path.join(config.ROOT, 'player_debug.log'), 'a') as fh:
                        fh.write(f'\n=== WORKER {target.__name__} CRASHED (pid {os.getpid()}) ===\n')
                        traceback.print_exc(file=fh)
                except Exception:
                    pass
                raise
        _guarded.__name__ = f'guarded_{target.__name__}'
        if os.name == 'nt':
            threading.Thread(target=_guarded, args=args, daemon=True,
                             name=f'worker-{target.__name__}').start()
        else:
            multiprocessing.get_context('fork').Process(target=_guarded, args=args).start()

    start_worker(threaderVideo)
    start_worker(threader, (num, arr))
    start_worker(YTQue_threader)
    recover_stuck_processing()
    start_worker(MetaQue_threader)
    start_worker(PlaylistQue_threader)
    start_worker(Backup_threader)
    appsettingAudioPlayFlagUpdate(1)
    appsettingVideoPlayFlagUpdate(1)
    appsettingYT_QuePlayFlagUpdate(1)
    appsettingFlagUpdate('meta_que_switch', 1)
    appsettingFlagUpdate('playlist_que_switch', 1)

    time.sleep(3)
    appsettingAudioPlayFlagUpdatePID(999999)
    appsettingYT_QuePlayFlagUpdatePID(999999)
    queue_next()


def _backfill_artists_async():
    import threading

    def _run():
        try:
            import media.media_facets as media_facets
            n = media_facets.backfill_sure_artists(config.DB_PATH)
            if n:
                print(f'[artists] filled {n} artists from metadata')
        except Exception as exc:
            print('[artists] backfill skipped:', exc)
    threading.Thread(target=_run, name='artist-backfill', daemon=True).start()


def start_integrations():
    """Relay + OBS bring-up (runs inside the server's lifespan, after the
    workers forked). Each guarded against boot loops by relay_guard."""
    from datetime import datetime as _dt
    from sql import appsettingGet, appsettingSet
    from core.appctx import ctx
    import core.db as _db

    _backfill_artists_async()

    if appsettingGet('relay_enabled', '0') == '1':
        import integrations.relay_guard as relay_guard
        if relay_guard.tripped():
            relay_guard.disarm()
            appsettingSet('relay_enabled', '0')
            appsettingSet('relay_boot_tripped', _dt.now().strftime('%Y-%m-%d %H:%M:%S'))
            print('*** Relay auto-start SKIPPED: the previous start crashed during '
                  'relay bring-up. Relay has been DISABLED — re-enable it from the '
                  'Relay page when ready. ***')
        else:
            relay_guard.arm()
            try:
                import integrations.relay_receiver as relay_receiver
                relay_receiver.start(ctx)
                import integrations.relay_ws as relay_ws
                relay_ws.start(ctx)
                with _db.session_scope():
                    import integrations.relay_broadcaster as relay_broadcaster
                    relay_broadcaster.push_all_characters()
                    relay_broadcaster.push_session_users()
                    relay_broadcaster.push_character_feeds()
                    relay_broadcaster.push_library()
            finally:
                relay_guard.disarm_after_grace()

    if appsettingGet('obs_enabled', '0') == '1':
        import integrations.relay_guard as relay_guard
        if relay_guard.tripped(relay_guard.OBS_GUARD_PATH):
            relay_guard.disarm(relay_guard.OBS_GUARD_PATH)
            appsettingSet('obs_enabled', '0')
            appsettingSet('obs_boot_tripped', _dt.now().strftime('%Y-%m-%d %H:%M:%S'))
            print('*** OBS auto-start SKIPPED: the previous start crashed during '
                  'OBS bring-up. OBS control has been DISABLED — re-enable it from '
                  'the Broadcast page when ready. ***')
        else:
            relay_guard.arm(relay_guard.OBS_GUARD_PATH)
            try:
                import integrations.obs_ws as obs_ws
                obs_ws.start(ctx)
                # The watchers live with the OBS router (drop-out watch,
                # auto-cam, dice reflow) — ctx stands in for the Flask app.
                import routers.obs as obs_watch
                obs_watch.start_feed_watch(ctx)
                obs_watch.start_dice_watch(ctx)
            finally:
                relay_guard.disarm_after_grace(relay_guard.OBS_GUARD_PATH)


def stop_integrations():
    for mod, fn in (('relay_receiver', 'stop'), ('relay_ws', 'stop'), ('obs_ws', 'stop'),
                    ('routers.obs', 'stop_feed_watch'), ('routers.obs', '_cancel_return')):
        try:
            m = sys.modules.get(mod)
            if m is not None:
                getattr(m, fn)()
        except Exception:
            pass
