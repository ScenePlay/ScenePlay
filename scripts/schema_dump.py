#!/usr/bin/env python3
"""Dump a normalised sqlite_master of the given database (default: a fresh
schema built by this app) — the format tests/test_schema_parity.py compares."""
import os
import sqlite3
import sys
import tempfile


def normalised(path):
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL "
                        "AND name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    conn.close()
    out = []
    for t, n, sql in rows:
        s = ' '.join(sql.split())
        s = s.replace('CREATE TABLE IF NOT EXISTS', 'CREATE TABLE')
        for a, b in ((' ,', ','), (', ', ','), (' (', '('), ('( ', '('), (' )', ')'), (') ', ')')):
            s = s.replace(a, b)
        out.append(f'{t} {n} {s}')
    return out


def fresh_schema_lines():
    d = tempfile.mkdtemp()
    path = os.path.join(d, 'fresh.db')
    os.environ['SP_DB_PATH'] = path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import core.db_migrate as db_migrate
    import core.events as events
    db_migrate.sync_schema(path)
    events.ensure_table(path)
    return normalised(path)


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else None
    src = sys.argv[2] if len(sys.argv) > 2 else None
    lines = normalised(src) if src else fresh_schema_lines()
    text = '\n'.join(lines) + '\n'
    if target:
        with open(target, 'w') as f:
            f.write(text)
        print(f'wrote {len(lines)} lines to {target}')
    else:
        sys.stdout.write(text)
