#!/usr/bin/env python3
"""Headless-browser smoke test of the SPA against a running instance:
loads /login, logs in, walks a few routes, and fails on any console error or
uncaught page error. Usage: spa_smoke.py http://127.0.0.1:8086 user pass [paths...]"""
import sys

from playwright.sync_api import sync_playwright

base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8086'
user = sys.argv[2] if len(sys.argv) > 2 else 'dm'
pw = sys.argv[3] if len(sys.argv) > 3 else 'x'
paths = sys.argv[4:] or ['/ttrpg', '/', '/scenes', '/ttrpg/change-password', '/nope']

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={'width': 390, 'height': 800})
    page.on('console', lambda m: errors.append(f'console.{m.type}: {m.text}') if m.type == 'error' else None)
    page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
    page.goto(base + '/login', wait_until='networkidle')
    if page.url.endswith('/ttrpg/setup'):
        page.fill('#su-username', user); page.fill('#su-display', 'DM'); page.fill('#su-password', pw)
        page.click('#setup-form button'); page.wait_for_url('**/ttrpg', timeout=10000)
    else:
        page.fill('#login-username', user); page.fill('#login-password', pw)
        page.click('#login-form button[type=submit]')
        page.wait_for_timeout(1500)
    print('after login:', page.url, '| title:', page.title())
    for path in paths:
        page.goto(base + path, wait_until='networkidle')
        page.wait_for_timeout(600)
        h = page.locator('h1,h2,h3,h4').first
        print(f'{path:32} -> {page.url.replace(base, ""):32} {page.title()[:40]!r} {(h.inner_text()[:40] if h.count() else "")!r}')
    page.goto(base + '/logout', wait_until='networkidle'); page.wait_for_timeout(500)
    print('after logout:', page.url)
    b.close()

bad = [e for e in errors if 'favicon' not in e]
print('\n'.join(bad) if bad else 'no console/page errors')
sys.exit(1 if bad else 0)
