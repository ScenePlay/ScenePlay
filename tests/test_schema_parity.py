"""The schema this app builds on an empty database must equal the one the
Flask app built (tests/fixtures/schema_0017.sql, dumped from a fresh Flask
boot), plus only the tables this port deliberately adds. Fails loudly when
DDL changes without a revision."""
import os
import subprocess
import sys

import core.config as config

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'schema_0017.sql')
ADDED_BY_PORT = {'tblEvents'}


def test_fresh_schema_matches_flask_fixture(tmp_path):
    with open(FIXTURE) as f:
        expected = [ln.rstrip('\n') for ln in f if ln.strip()]
    env = dict(os.environ, SP_DB_PATH=str(tmp_path / 'fresh.db'), SP_INSTANCE_DIR=str(tmp_path / 'inst'))
    out = subprocess.run([sys.executable, os.path.join(config.ROOT, 'scripts', 'schema_dump.py')],
                         capture_output=True, text=True, env=env, cwd=config.ROOT, timeout=120)
    assert out.returncode == 0, out.stderr[-2000:]
    got = [ln for ln in out.stdout.splitlines() if ln.strip()]
    extra = [ln for ln in got if ln not in expected]
    missing = [ln for ln in expected if ln not in got]
    assert not missing, 'missing vs Flask:\n' + '\n'.join(missing)
    unexpected = [ln for ln in extra if ln.split(' ', 2)[1] not in ADDED_BY_PORT]
    assert not unexpected, 'unexpected DDL:\n' + '\n'.join(unexpected)
