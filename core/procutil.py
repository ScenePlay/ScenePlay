import os


def pid_alive(pid):
    """True if a process with this pid is currently running.

    The workers use this to ask "is the previous player/downloader still
    going?". On POSIX that's os.kill(pid, 0). On Windows os.kill(pid, 0) is
    NOT a probe — signal 0 is CTRL_C_EVENT, so it *sends* a console interrupt
    and usually reports success for any pid, which made the workers think a
    long-dead process was still running (queued downloads never started).
    OpenProcess + a zero-timeout wait is the real Windows liveness check.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        SYNCHRONIZE = 0x100000
        WAIT_TIMEOUT = 0x102          # still running when asked to wait 0ms
        handle = kernel32.OpenProcess(SYNCHRONIZE, 0, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        # Includes EPERM: the old bare-except probes also treated any error
        # as "not running", so keep that behavior identical on Linux.
        return False
    return True


# ── uptime (Utilities page, /isAlive) ─────────────────────────────────────────

def fmt_duration(seconds):
    """Whole seconds -> '3d 4h 12m' / '1h 0m' / '5m' (minutes resolution)."""
    s = max(0, int(seconds))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f'{d}d {h}h {m}m'
    if h:
        return f'{h}h {m}m'
    return f'{m}m'


def uptime_info():
    """Server = OS boot; app = THIS web process's start (psutil, so it is right
    on Linux, the Pi and Windows regardless of import order and resets on
    every watchdog/Update restart). Timestamps use the app's local format."""
    import time
    import psutil
    now = time.time()
    boot = psutil.boot_time()
    started = psutil.Process(os.getpid()).create_time()
    fmt = lambda t: time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))   # noqa: E731
    return {
        'server_boot': fmt(boot), 'server_uptime_s': int(now - boot),
        'server_uptime': fmt_duration(now - boot),
        'app_started': fmt(started), 'app_uptime_s': int(now - started),
        'app_uptime': fmt_duration(now - started),
    }
