"""JWT dependencies: bearer vs ?token= (GET only), 401/403 envelope, password
version invalidation, refresh, setup lock, DM-only user management."""
from tests.conftest import auth


def test_anonymous_is_401_json(client):
    r = client.get('/api/v1/users')
    assert r.status_code == 401
    assert r.json() == {'error': 'login required', 'code': 'login_required', 'detail': None}


def test_player_is_403_on_dm_routes(client, player_token):
    r = client.get('/api/v1/users', headers=auth(player_token))
    assert r.status_code == 403 and r.json()['code'] == 'dm_required'


def test_dm_bearer_ok(client, dm_token):
    assert client.get('/api/v1/users', headers=auth(dm_token)).status_code == 200


def test_query_token_only_on_get(client, dm_token):
    assert client.get(f'/api/v1/users?token={dm_token}').status_code == 200
    r = client.post(f'/api/v1/users/1/reset-password?token={dm_token}', json={'new_password': 'x'})
    assert r.status_code == 401


def test_garbage_token_is_anonymous(client):
    r = client.get('/api/v1/auth/bootstrap', headers=auth('not.a.jwt'))
    assert r.status_code == 200 and r.json()['user'] is None


def test_password_change_invalidates_old_token(client, player, player_token):
    ok = client.get('/api/v1/auth/bootstrap', headers=auth(player_token)).json()['user']
    assert ok and ok['username'] == 'testplayer'
    r = client.post('/api/v1/auth/change-password', headers=auth(player_token),
                    json={'current_password': 'pw', 'new_password': 'pw2', 'confirm_password': 'pw2'})
    assert r.status_code == 200 and r.json()['token']
    assert client.get('/api/v1/auth/bootstrap', headers=auth(player_token)).json()['user'] is None
    assert client.get('/api/v1/auth/bootstrap', headers=auth(r.json()['token'])).json()['user']['username'] == 'testplayer'
    # restore for other tests
    client.post('/api/v1/auth/change-password', headers=auth(r.json()['token']),
                json={'current_password': 'pw2', 'new_password': 'pw', 'confirm_password': 'pw'})


def test_login_and_refresh(client, dm):
    r = client.post('/api/v1/auth/login', json={'username': 'testdm', 'password': 'pw'})
    assert r.status_code == 200 and r.json()['user']['role'] == 'dm'
    tok = r.json()['token']
    r2 = client.post('/api/v1/auth/refresh', headers=auth(tok))
    assert r2.status_code == 200 and r2.json()['token']
    bad = client.post('/api/v1/auth/login', json={'username': 'testdm', 'password': 'nope'})
    assert bad.status_code == 401 and bad.json()['code'] == 'bad_credentials'


def test_short_ttl_token(client, dm):
    from security.jwt import verify_token
    r = client.post('/api/v1/auth/login', json={'username': 'testdm', 'password': 'pw', 'ttl_hours': 12})
    c = verify_token(r.json()['token'])
    assert 0 < c['exp'] - c['iat'] <= 12 * 3600


def test_setup_locked_once_users_exist(client, dm):
    r = client.post('/api/v1/auth/setup', json={'username': 'x', 'display_name': 'X', 'password': 'y'})
    assert r.status_code == 409 and r.json()['code'] == 'setup_done'


def test_user_management(client, dm, dm_token):
    r = client.post('/api/v1/users', headers=auth(dm_token),
                    json={'username': 'newp', 'display_name': 'New P', 'password': 'p', 'role': 'player'})
    assert r.status_code == 200
    uid = r.json()['user']['user_id']
    dup = client.post('/api/v1/users', headers=auth(dm_token),
                      json={'username': 'newp', 'display_name': 'New P', 'password': 'p'})
    assert dup.status_code == 400 and 'already taken' in dup.json()['error']
    r = client.post(f'/api/v1/users/{uid}/edit', headers=auth(dm_token), json={'username': 'newp2', 'display_name': 'Renamed'})
    assert r.status_code == 200 and 'newp2' in r.json()['message']
    r = client.post(f'/api/v1/users/{dm.user_id}/delete', headers=auth(dm_token))
    assert r.status_code == 400 and 'own account' in r.json()['error']
    r = client.post(f'/api/v1/users/{uid}/delete', headers=auth(dm_token))
    assert r.status_code == 200 and r.json()['ok']
    assert client.post(f'/api/v1/users/{uid}/delete', headers=auth(dm_token)).status_code == 404


def test_validation_error_envelope(client):
    r = client.post('/api/v1/auth/login', json={'username': ''})
    assert r.status_code == 422 and r.json()['code'] == 'validation'
