"""No-bundler safety net: every asset the SPA references must resolve, no
Jinja leftovers, every route serves the shell, cache headers as designed."""
import os
import re

import pytest

import core.config as config

WEB = config.WEB_DIR


def _read(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def test_index_served(client):
    r = client.get('/')
    assert r.status_code == 200
    assert 'text/html' in r.headers['content-type']
    assert '/app/main.js' in r.text


def test_index_assets_resolve(client):
    html = _read(os.path.join(WEB, 'index.html'))
    refs = re.findall(r'(?:src|href)="(/[^"]+)"', html)
    assert refs
    for ref in refs:
        r = client.get(ref)
        assert r.status_code == 200, ref
        if ref.endswith('.js'):
            assert 'javascript' in r.headers['content-type'], ref
        if ref.endswith('.css'):
            assert 'text/css' in r.headers['content-type'], ref


def _module_files():
    for root, _dirs, files in os.walk(os.path.join(WEB, 'app')):
        for f in files:
            if f.endswith('.js'):
                yield os.path.join(root, f)


def test_module_imports_resolve(client):
    missing = []
    for path in _module_files():
        src = _read(path)
        url_dir = '/' + os.path.relpath(os.path.dirname(path), WEB).replace(os.sep, '/')
        specs = re.findall(r"""import\s+(?:[^'"]*?from\s+)?['"]([^'"]+)['"]""", src)
        specs += re.findall(r"""import\(\s*['"]([^'"]+)['"]\s*\)""", src)
        specs += re.findall(r"""load(?:Script|Css)\(\s*['"]([^'"]+)['"]""", src)
        for spec in specs:
            if spec.startswith('http'):
                continue
            if spec.startswith('/'):
                url = spec
            else:
                url = os.path.normpath(os.path.join(url_dir, spec)).replace(os.sep, '/')
            fs = os.path.join(WEB, url.lstrip('/'))
            if not os.path.isfile(fs):
                missing.append(f'{os.path.relpath(path, WEB)} -> {spec} (no file {url})')
                continue
            r = client.get(url)
            if r.status_code != 200:
                missing.append(f'{os.path.relpath(path, WEB)} -> {spec} ({r.status_code})')
    assert not missing, '\n'.join(missing)


def test_dynamic_view_imports_exist():
    """routes.js lazy-loads ./views/<p>.js — every referenced view must exist."""
    src = _read(os.path.join(WEB, 'app', 'routes.js'))
    missing = []
    for p in re.findall(r"""V\('([^']+)'\)""", src):
        if not os.path.isfile(os.path.join(WEB, 'app', 'views', p + '.js')):
            missing.append(p)
    assert not missing, missing


def test_no_jinja_leftovers():
    bad = []
    for root, _dirs, files in os.walk(WEB):
        rel = os.path.relpath(root, WEB).replace(os.sep, '/')
        if rel.startswith(('vendor', 'shared')) or '/vendor' in rel or '/shared' in rel:
            continue
        for f in files:
            if not f.endswith(('.js', '.html', '.css')):
                continue
            src = _read(os.path.join(root, f))
            for needle in ('url_for(', '{{ ', '{% ', 'static/scripts/'):
                if needle in src:
                    bad.append(f'{os.path.relpath(os.path.join(root, f), WEB)}: {needle}')
    assert not bad, '\n'.join(bad)


def test_no_lit_boolean_attribute_syntax():
    """dom.js's html`` is a string template: lit's `?attr=${bool}` renders as
    a bogus attribute the browser ignores. The producer console's transition
    selects were painted that way and snapped to their first entry on every
    repaint (so Cut/Fade never seemed to stick)."""
    pat = re.compile(r'\?(selected|checked|disabled|hidden)=')
    bad = []
    for root, _dirs, files in os.walk(os.path.join(WEB, 'app')):
        if 'vendor' in root.replace(os.sep, '/').split('/'):
            continue
        for f in files:
            if f.endswith('.js') and pat.search(_read(os.path.join(root, f))):
                bad.append(os.path.relpath(os.path.join(root, f), WEB))
    assert not bad, bad


def test_every_route_serves_shell(client):
    src = _read(os.path.join(WEB, 'app', 'routes.js'))
    paths = re.findall(r"""path:\s*'([^']+)'""", src)
    assert paths
    for p in paths:
        url = re.sub(r':[A-Za-z_]+', '1', p)
        r = client.get(url, headers={'Accept': 'text/html'})
        assert r.status_code == 200 and '/app/main.js' in r.text, url


def test_cache_headers(client):
    assert 'no-cache' in client.get('/app/main.js').headers.get('cache-control', '')
    assert 'max-age' in client.get('/vendor/gridjs.umd.js').headers.get('cache-control', '')


def test_topics_match_backend():
    import core.events as events
    src = _read(os.path.join(WEB, 'app', 'topics.js'))
    names = re.findall(r"'([a-z]+)'", src.split('PARAM_PREFIXES')[0])
    assert set(names) == events.TOPICS


def test_producer_console_route_and_modules(client, dm_token):
    r = client.get('/ttrpg/producer', headers={'Authorization': f'Bearer {dm_token}'})
    assert r.status_code == 200 and '/app/main.js' in r.text
    for f in ('web/app/views/ttrpg/producer/index.js', 'web/app/views/ttrpg/producer/template.js',
              'web/app/views/ttrpg/producer/console.js', 'web/css/views/producer.css'):
        assert __import__('os').path.exists(f), f
    routes = open('web/app/routes.js', encoding='utf-8').read()
    assert "path: '/ttrpg/producer'" in routes and "bodyClass: 'producer'" in routes


def test_gridjs_theme_loads_before_sp_core():
    """The Grid.js stock theme (mermaid.min.css) is what gives every table its
    header band, sort arrows, cell padding and row lines. 1.x loaded it from
    static/css; the SPA shell must ship it under /vendor and load it BEFORE
    sp-core.css, whose overrides assume they come second."""
    html = _read(os.path.join(WEB, 'index.html'))
    refs = re.findall(r'href="(/[^"]+\.css)"', html)
    assert '/vendor/gridjs-mermaid.min.css' in refs
    assert refs.index('/vendor/gridjs-mermaid.min.css') < refs.index('/css/sp-core.css')
    css = _read(os.path.join(WEB, 'vendor', 'gridjs-mermaid.min.css'))
    for cls in ('.gridjs-sort-asc', '.gridjs-sort-desc', '.gridjs-sort-neutral', 'th.gridjs-th', 'td.gridjs-td'):
        assert cls in css, cls
