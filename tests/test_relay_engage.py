"""Enable Relay asks which session to engage: keep the join code the players
already have ('reuse'), mint a new one ('new'), or — legacy plain enable —
leave the relay session alone ('')."""
import os

import pytest

from core.db import db

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture()
def relay_app(monkeypatch, legacy_app):
    import sys, types
    from models.user import tblUsers
    import core.config as config
    import routers.relay_admin as ra
    monkeypatch.setattr(config, 'INTEGRATIONS', True)     # conftest runs with SP_INTEGRATIONS=0
    calls = []
    settings = {'relay_enabled': '0', 'relay_session_id': 'sid-old', 'relay_session_code': 'ABC123'}
    monkeypatch.setattr(ra, 'appsettingGet', lambda k, d='': settings.get(k, d))
    monkeypatch.setattr(ra, 'appsettingSet', lambda k, v: settings.__setitem__(k, v))
    monkeypatch.setattr(ra, '_start_session', lambda requested_id=None, requested_code=None:
                        (calls.append(('start', requested_id, requested_code)) or ('NEWCODE' if not requested_code else requested_code, requested_id or 'sid-new')))
    monkeypatch.setattr(ra, '_start_receiver', lambda: calls.append(('receiver',)))
    monkeypatch.setattr(ra, '_emit_relay', lambda: None)
    for name, attrs in (('relay_guard', {'arm': lambda: None, 'disarm_after_grace': lambda: None}),
                        ('relay_ws', {'start': lambda app: None, 'restart': lambda: None, 'stop': lambda: None}),
                        ('relay_broadcaster', {k: (lambda k=k: calls.append(('push', k))) for k in
                                               ('push_all_characters', 'push_session_users', 'push_character_feeds', 'push_library')})):
        m = types.ModuleType(name); [setattr(m, k, v) for k, v in attrs.items()]
        from tests.conftest import fake_module
        fake_module(monkeypatch, 'integrations.' + name, m)

    dm = tblUsers(username='gm', display_name='GM', password_hash='x', role='dm',
                  active=1, created_at='2026-01-01 00:00:00')
    db.session.add(dm); db.session.commit()
    yield legacy_app, dm, settings, calls


def _enable(relay_app, mode):
    a, dm, settings, calls = relay_app
    r = a.test_client(user=dm).post('/ttrpg/relay/toggle', data={'session_mode': mode})
    assert r.status_code == 200 and settings['relay_enabled'] == '1'
    body = r.get_json()
    assert body['ok'] is True and body['enabled'] is True and 'Relay enabled' in body['message']
    return calls


def test_reuse_keeps_existing_identity(relay_app):
    calls = _enable(relay_app, 'reuse')
    assert ('start', 'sid-old', 'ABC123') in calls
    assert not [c for c in calls if c[0] == 'push']     # _start_session pushed already


def test_new_mints_fresh_code(relay_app):
    calls = _enable(relay_app, 'new')
    assert ('start', None, None) in calls


def test_reuse_without_previous_code_falls_back_to_new(relay_app):
    a, dm, settings, calls = relay_app
    settings['relay_session_code'] = ''
    _enable(relay_app, 'reuse')
    assert ('start', None, None) in calls


def test_plain_enable_leaves_session_alone(relay_app):
    calls = _enable(relay_app, '')
    assert not [c for c in calls if c[0] == 'start']
    assert ('push', 'push_all_characters') in calls


def test_json_body_works_like_the_form(relay_app):
    """The SPA submits the toggle form as JSON."""
    a, dm, settings, calls = relay_app
    r = a.test_client(user=dm).post('/ttrpg/relay/toggle', json={'session_mode': 'reuse'})
    assert r.status_code == 200 and ('start', 'sid-old', 'ABC123') in calls


def test_disable_stops_the_receiver(relay_app):
    a, dm, settings, calls = relay_app
    settings['relay_enabled'] = '1'
    r = a.test_client(user=dm).post('/ttrpg/relay/toggle', data={'session_mode': ''})
    assert r.status_code == 200 and settings['relay_enabled'] == '0'
    assert r.get_json()['message'] == 'Relay disabled.' and r.get_json()['enabled'] is False


def test_toggle_is_dm_only(relay_app):
    a, dm, settings, calls = relay_app
    from models.user import tblUsers
    pl = tblUsers(username='pl', display_name='PL', password_hash='x', role='player',
                  active=1, created_at='2026-01-01 00:00:00')
    db.session.add(pl); db.session.commit()
    r = a.test_client(user=pl).post('/ttrpg/relay/toggle', data={'session_mode': 'new'})
    assert r.status_code == 403 and r.get_json()['code'] == 'dm_required'
    assert settings['relay_enabled'] == '0'


def test_status_view_carries_the_prompt():
    src = open(os.path.join(REPO, 'web', 'app', 'views', 'ttrpg', 'relay_status.js'), encoding='utf-8').read()
    assert 'spPickOption(' in src and 'name="session_mode"' in src
    assert 'window.prompt' not in src                   # Eric's rule: dropdown, never a typed number
