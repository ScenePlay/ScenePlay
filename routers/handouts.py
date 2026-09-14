"""PDF handouts (ported from routes/handouts.py): upload any PDF to the box
and read it in a page-turning viewer (Utilities → Handouts).

Files land under static/uploads/handouts/<uuid>.pdf so they ride along with
Backup → Restore like every other upload folder; rows live in tblHandouts
(models/ttrpg.py). Rendering is entirely client-side (vendored pdf.js in
web/vendor/pdfjs/ + web/legacy/handout_reader.js) — no server-side PDF
parser, so the page count is reported back by the viewer the first time a
document opens. Everything here is DM-only, like the rest of Utilities; the
PDF bytes also accept a short-lived signed URL (the page data carries one)
because pdf.js fetches the file itself."""
import os
import re
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import core.config as config
from core.db import db
from models.ttrpg import tblHandoutBookmarks, tblHandouts
from routers._util import _now, form_or_json
from security.deps import ApiError, require_dm, require_dm_or_signed, signed_url

router = APIRouter(prefix='/handouts')
api = APIRouter(prefix='/api/v1/handouts')

UPLOAD_FOLDER = os.path.join(config.UPLOADS_DIR, 'handouts')
# Rulebooks run 50-100 MB; bigger than this is almost certainly a mistake
# (and would take a Pi minutes to accept). Reverse proxies cap uploads too —
# scripts/setup mentions the nginx client_max_body_size fix.
MAX_PDF_BYTES = 300 * 1024 * 1024
TITLE_MAX = 120
LABEL_MAX = 80
FILENAME_RE = re.compile(r'^[0-9a-f]{32}\.pdf$')
FILE_URL_TTL_S = 6 * 3600      # a reading session; the SPA re-fetches page data on reload


def _upload_dir():
    return UPLOAD_FOLDER if os.path.isabs(UPLOAD_FOLDER) else os.path.join(config.ROOT, UPLOAD_FOLDER)


def _file_path(row):
    return os.path.join(_upload_dir(), row.filename)


def _clean_title(raw, fallback):
    title = re.sub(r'\s+', ' ', str(raw or '')).strip()
    if not title:
        title = fallback
    return title[:TITLE_MAX]


def _title_from_filename(name):
    base = os.path.splitext(os.path.basename(str(name or '')))[0]
    base = re.sub(r'[_\-]+', ' ', base).strip()
    return base or 'Untitled handout'


def _human_size(n):
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def _bookmark_view(bm):
    return {'id': bm.bookmark_id, 'page': bm.page, 'label': bm.label,
            'created_at': bm.created_at}


def _bookmarks(row):
    return [_bookmark_view(b) for b in sorted(row.bookmarks, key=lambda b: (b.page, b.bookmark_id))]


def _row_view(row):
    return {
        'id': row.handout_id,
        'title': row.title,
        'filename': row.filename,
        'size_h': _human_size(row.size_bytes),
        'page_count': row.page_count,
        'last_page': row.last_page or 1,
        'created_at': row.created_at,
        'on_disk': os.path.isfile(_file_path(row)),
        'bookmarks': _bookmarks(row),
    }


def _clamp_page(row, raw):
    """A page number from the client: int, >= 1, and never past the known
    page count (0 when unusable)."""
    try:
        page = int(raw or 0)
    except (TypeError, ValueError):
        return 0
    if page < 1:
        return 0
    if row.page_count:
        page = min(page, row.page_count)
    return page


def _clean_label(raw, fallback):
    label = re.sub(r'\s+', ' ', str(raw or '')).strip()
    return (label or fallback)[:LABEL_MAX]


def _not_found():
    return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)


@api.get('')
def index(user=Depends(require_dm)):
    rows = tblHandouts.query.order_by(tblHandouts.title.collate('NOCASE')).all()
    return {'handouts': [dict(_row_view(r), file_url_dl=file_url(r, dl=True)) for r in rows],
            'max_mb': MAX_PDF_BYTES // (1024 * 1024)}


def _save_pdf(f, title):
    """Validate + store an uploaded PDF. Returns (row, error)."""
    if f is None or not f.filename:
        return None, 'choose a PDF file'
    src = f.file
    head = src.read(5)
    src.seek(0)
    # The magic number is the real check; the extension is just a hint.
    if not head.startswith(b'%PDF'):
        return None, 'that file is not a PDF'
    raw = src.read()
    if len(raw) > MAX_PDF_BYTES:
        return None, f'PDF is larger than {MAX_PDF_BYTES // (1024 * 1024)} MB'
    if not raw:
        return None, 'empty file'
    filename = f'{uuid.uuid4().hex}.pdf'
    dest = _upload_dir()
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, filename), 'wb') as out:
        out.write(raw)
    row = tblHandouts(title=_clean_title(title, _title_from_filename(f.filename)),
                      filename=filename, size_bytes=len(raw), last_page=1,
                      created_at=_now())
    db.session.add(row)
    db.session.commit()
    return row, None


@router.post('/upload')
def upload(form: dict = Depends(form_or_json), pdf: UploadFile = File(None), user=Depends(require_dm)):
    row, err = _save_pdf(pdf, form.get('title'))
    if err:
        return JSONResponse({'ok': False, 'error': err}, status_code=400)
    return {'ok': True, 'handout': _row_view(row), 'message': f'Uploaded "{row.title}".'}


@router.post('/{handout_id}/rename')
def rename(handout_id: int, data: dict = Depends(form_or_json), user=Depends(require_dm)):
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        return _not_found()
    row.title = _clean_title(data.get('title'), row.title)
    row.updated_at = _now()
    db.session.commit()
    return {'ok': True, 'title': row.title}


@router.post('/{handout_id}/delete')
def delete(handout_id: int, user=Depends(require_dm)):
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        return _not_found()
    try:
        if os.path.isfile(_file_path(row)):
            os.remove(_file_path(row))
    except OSError:
        pass
    db.session.delete(row)
    db.session.commit()
    return {'ok': True}


@router.get('/{handout_id}/file')
def file(handout_id: int, dl: str = '', user=Depends(require_dm_or_signed)):
    """The PDF bytes. Served through the guard (not as a bare static URL) so
    a handout is never readable without a DM token or a signed link; inline
    so pdf.js can fetch it and a plain browser tab can still open it."""
    row = db.session.get(tblHandouts, handout_id)
    if row is None or not FILENAME_RE.match(row.filename):
        raise ApiError(404, 'not found', code='not_found')
    if not os.path.isfile(_file_path(row)):
        raise ApiError(404, 'not found', code='not_found')
    return FileResponse(_file_path(row), media_type='application/pdf',
                        filename=f'{row.title}.pdf',
                        content_disposition_type='attachment' if dl == '1' else 'inline')


def file_url(row, dl=False):
    """A signed link to the PDF bytes: pdf.js / <a href> cannot send a bearer."""
    path = f'/handouts/{row.handout_id}/file' + ('?dl=1' if dl else '')
    return signed_url(path, ttl_s=FILE_URL_TTL_S)


@api.get('/{handout_id}')
def read(handout_id: int, page: str = None, user=Depends(require_dm)):
    """Reader page data. ?page=N (a bookmark link from the list page) opens
    there instead of at the resume point; the viewer clamps again once it
    knows the real count."""
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        raise ApiError(404, 'not found', code='not_found')
    if not os.path.isfile(_file_path(row)):
        return {'redirect': '/handouts',
                'message': f'"{row.title}" is missing on disk — restore it or upload again.'}
    view = _row_view(row)
    start = _clamp_page(row, page)
    return {'handout': view, 'start_page': start or view['last_page'],
            'file_url': file_url(row),
            'progress_url': f'/handouts/{row.handout_id}/progress',
            'bookmarks_url': f'/handouts/{row.handout_id}/bookmarks'}


@router.post('/{handout_id}/progress')
def progress(handout_id: int, data: dict = Depends(form_or_json), user=Depends(require_dm)):
    """Reader state from the viewer: {page, page_count}. Page is clamped to
    the known count so a stale tab can't park the bookmark off the end."""
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        return _not_found()
    try:
        count = int(data.get('page_count') or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        row.page_count = count
    try:
        page = int(data.get('page') or 0)
    except (TypeError, ValueError):
        page = 0
    if page > 0:
        if row.page_count:
            page = min(page, row.page_count)
        row.last_page = page
    row.updated_at = _now()
    db.session.commit()
    return {'ok': True, 'last_page': row.last_page, 'page_count': row.page_count}


# ---------------------------------------------------------------------------
# Bookmarks — one named marker per page (tblHandoutBookmarks)
# ---------------------------------------------------------------------------

@router.get('/{handout_id}/bookmarks')
def bookmarks(handout_id: int, user=Depends(require_dm)):
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        return _not_found()
    return {'ok': True, 'bookmarks': _bookmarks(row)}


@router.post('/{handout_id}/bookmarks')
def bookmark_add(handout_id: int, data: dict = Depends(form_or_json), user=Depends(require_dm)):
    """{page, label?}: add a bookmark on `page`, or — since a page carries at
    most one — rename the existing one when a label is sent. Returns the
    bookmark plus the full (page-ordered) list so the viewer just replaces
    its copy."""
    row = db.session.get(tblHandouts, handout_id)
    if row is None:
        return _not_found()
    page = _clamp_page(row, data.get('page'))
    if not page:
        return JSONResponse({'ok': False, 'error': 'page must be a number from 1'}, status_code=400)
    existing = next((b for b in row.bookmarks if b.page == page), None)
    created = existing is None
    if existing is None:
        existing = tblHandoutBookmarks(handout_id=row.handout_id, page=page,
                                       label=_clean_label(data.get('label'), f'Page {page}'),
                                       created_at=_now())
        db.session.add(existing)
    elif data.get('label') is not None:
        existing.label = _clean_label(data.get('label'), existing.label)
    row.updated_at = _now()
    db.session.commit()
    return {'ok': True, 'created': created, 'bookmark': _bookmark_view(existing),
            'bookmarks': _bookmarks(row)}


@router.post('/{handout_id}/bookmarks/{bookmark_id}/rename')
def bookmark_rename(handout_id: int, bookmark_id: int, data: dict = Depends(form_or_json), user=Depends(require_dm)):
    bm = db.session.get(tblHandoutBookmarks, bookmark_id)
    if bm is None or bm.handout_id != handout_id:
        return _not_found()
    bm.label = _clean_label(data.get('label'), bm.label)
    bm.handout.updated_at = _now()
    db.session.commit()
    return {'ok': True, 'bookmark': _bookmark_view(bm), 'bookmarks': _bookmarks(bm.handout)}


@router.post('/{handout_id}/bookmarks/{bookmark_id}/delete')
def bookmark_delete(handout_id: int, bookmark_id: int, user=Depends(require_dm)):
    bm = db.session.get(tblHandoutBookmarks, bookmark_id)
    if bm is None or bm.handout_id != handout_id:
        return _not_found()
    row = bm.handout
    db.session.delete(bm)
    row.updated_at = _now()
    db.session.commit()
    return {'ok': True, 'bookmarks': _bookmarks(row)}


open_router = api
