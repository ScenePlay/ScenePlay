"""Server (OS boot) and app (web process) uptime: core.procutil.uptime_info()
feeds /isAlive and the Utilities page."""
import os
import re
import time

from core.procutil import uptime_info, fmt_duration

TS = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')      # routers/_util._now format


def test_fmt_duration_days_hours_minutes():
    assert fmt_duration(3 * 86400 + 4 * 3600 + 12 * 60 + 5) == '3d 4h 12m'
    assert fmt_duration(3600) == '1h 0m'
    assert fmt_duration(65) == '1m'
    assert fmt_duration(0) == '0m'
    assert fmt_duration(-7) == '0m'


def test_uptime_info_shape_and_ordering():
    u = uptime_info()
    assert TS.match(u['server_boot']) and TS.match(u['app_started'])
    assert isinstance(u['server_uptime_s'], int) and isinstance(u['app_uptime_s'], int)
    assert 0 <= u['app_uptime_s'] <= u['server_uptime_s']
    assert u['server_boot'] <= u['app_started']          # the box booted before this process
    assert u['app_uptime'] == fmt_duration(u['app_uptime_s'])
    assert u['server_uptime'] == fmt_duration(u['server_uptime_s'])


def test_app_uptime_is_this_process():
    import psutil
    started = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(psutil.Process(os.getpid()).create_time()))
    assert uptime_info()['app_started'] == started


def test_isalive_reports_uptime(client):
    d = client.get('/isAlive').json()
    assert d['pid'] == os.getpid()
    assert TS.match(d['uptime']['app_started']) and 'server_uptime' in d['uptime']


def test_utilities_page_carries_uptime(client, dm_token):
    u = client.get('/api/v1/utilities', headers={'Authorization': f'Bearer {dm_token}'}).json()
    assert {'server_boot', 'server_uptime', 'app_started', 'app_uptime'} <= set(u['uptime'])
