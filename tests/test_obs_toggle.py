"""The Broadcast page's Enable button under SP_INTEGRATIONS=0.

A dev instance never dials a real OBS, so enabling there must say so instead of
flipping the switch and promising "connecting" (which is how an F5 session on
this PC looked like a broken OBS connection). Disabling stays local and works,
exactly like the relay toggle.
"""
import pytest

from core.db import db


@pytest.fixture()
def dm_client(legacy_app):
    from models.user import tblUsers
    dm = tblUsers(username='gm', display_name='GM', password_hash='x',
                  role='dm', active=1, created_at='2026-01-01 00:00:00')
    db.session.add(dm)
    db.session.commit()
    with legacy_app.test_client(user=dm) as c:
        yield c


@pytest.fixture()
def rig(monkeypatch):
    """Settings dict + recording stubs of everything toggle() can reach."""
    import routers.obs as obs
    import integrations.obs_ws as obs_ws
    import integrations.relay_guard as relay_guard
    settings = {}
    calls = []
    monkeypatch.setattr(obs, 'appsettingGet', lambda k, d=None: settings.get(k, d))
    monkeypatch.setattr(obs, 'appsettingSet', lambda k, v, *a: settings.__setitem__(k, str(v)))
    monkeypatch.setattr(obs_ws, 'start', lambda app: calls.append('start'))
    monkeypatch.setattr(obs_ws, 'stop', lambda: calls.append('stop'))
    monkeypatch.setattr(obs, 'start_feed_watch', lambda app: calls.append('feed'))
    monkeypatch.setattr(obs, 'start_dice_watch', lambda app: calls.append('dice'))
    monkeypatch.setattr(obs, 'stop_feed_watch', lambda: calls.append('stop_feed'))
    monkeypatch.setattr(obs, '_cancel_return', lambda: calls.append('cancel_return'))
    monkeypatch.setattr(obs, '_emit', lambda *a, **k: None)
    monkeypatch.setattr(relay_guard, 'arm', lambda *a, **k: None)
    monkeypatch.setattr(relay_guard, 'disarm_after_grace', lambda *a, **k: None)
    return {'settings': settings, 'calls': calls}


def test_enable_is_refused_when_integrations_are_off(dm_client, rig, monkeypatch):
    import core.config as config
    monkeypatch.setattr(config, 'INTEGRATIONS', False)
    rig['settings']['obs_enabled'] = '0'
    r = dm_client.post('/ttrpg/obs/toggle')
    body = r.get_json()
    assert r.status_code == 200 and body['ok'] is False and body['enabled'] is False
    assert 'SP_INTEGRATIONS=0' in body['message']
    assert rig['settings']['obs_enabled'] == '0'
    assert rig['calls'] == []


def test_disable_still_works_when_integrations_are_off(dm_client, rig, monkeypatch):
    import core.config as config
    monkeypatch.setattr(config, 'INTEGRATIONS', False)
    rig['settings']['obs_enabled'] = '1'
    r = dm_client.post('/ttrpg/obs/toggle')
    body = r.get_json()
    assert body == {'ok': True, 'enabled': False, 'message': 'OBS control disabled.'}
    assert rig['settings']['obs_enabled'] == '0'
    assert rig['calls'] == ['stop', 'stop_feed', 'cancel_return']


def test_enable_starts_the_manager_when_integrations_are_on(dm_client, rig, monkeypatch):
    import core.config as config
    monkeypatch.setattr(config, 'INTEGRATIONS', True)
    rig['settings']['obs_enabled'] = '0'
    r = dm_client.post('/ttrpg/obs/toggle')
    body = r.get_json()
    assert body['ok'] is True and body['enabled'] is True
    assert rig['settings']['obs_enabled'] == '1'
    assert rig['calls'] == ['start', 'feed', 'dice']
