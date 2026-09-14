"""Small helpers shared across router modules (ported from routes/_util.py)."""
import os
import uuid
from datetime import datetime

from fastapi import Request


async def json_body(request: Request) -> dict:
    """Lenient JSON body (like request.get_json(silent=True) or {})."""
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {'_': data}


async def json_any(request: Request):
    """JSON body of any shape, None when absent/invalid."""
    try:
        return await request.json()
    except Exception:
        return None


async def form_or_json(request: Request) -> dict:
    """Form fields (urlencoded/multipart) or a JSON object as a plain dict —
    the ported `request.form.get(...)` sites read `form.get(...)`. Uploaded
    files are included under their field name."""
    ctype = (request.headers.get('content-type') or '').lower()
    if 'application/json' in ctype:
        return await json_body(request)
    try:
        form = await request.form()
    except Exception:
        return {}
    out = {}
    for k in form.keys():
        vals = form.getlist(k)
        out[k] = vals[0] if len(vals) == 1 else vals
    out['__getlist__'] = form.getlist
    return out


def save_upload_downscaled(file_storage, dest_dir, max_dim=1024):
    """Save an uploaded image downscaled to `max_dim` on the long side.
    Accepts a Starlette UploadFile or anything with .filename/.read().
    Returns the saved filename (uuid + chosen extension)."""
    from integrations.relay_broadcaster import _downscale_image
    orig_ext = (file_storage.filename.rsplit('.', 1)[-1].lower()
                if file_storage.filename and '.' in file_storage.filename else 'png')
    src = getattr(file_storage, 'file', None) or file_storage
    raw = src.read()
    out, ext = _downscale_image(raw, orig_ext, max_dim)
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(dest_dir, exist_ok=True)
    with open(os.path.join(dest_dir, filename), 'wb') as f:
        f.write(out)
    return filename


def _now():
    """Local wall-clock timestamp, 'YYYY-MM-DD HH:MM:SS'. Single definition:
    stored in created_at / rolled_at columns and compared during relay sync."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def campaign_scene_ids(campaign_filter):
    from extensions import db
    from models.scenes import tblscenes as sc
    q = db.session.query(sc.scene_ID)
    if campaign_filter == -1:
        return q.filter(db.or_(sc.campaign_id.is_(None), sc.campaign_id == 0))
    return q.filter(sc.campaign_id == campaign_filter)


def scenes_for_filter(campaign_filter):
    from extensions import db
    from models.scenes import tblscenes as sc
    q = sc.query.with_entities(sc.scene_ID, sc.sceneName)
    if campaign_filter == -1:
        q = q.filter(db.or_(sc.campaign_id.is_(None), sc.campaign_id == 0))
    elif campaign_filter:
        q = q.filter(sc.campaign_id == campaign_filter)
    return q.order_by(sc.sceneName).all()


def campaigns_for_filter():
    from models.campaigns import tblcampaigns as cp
    return (cp.query.with_entities(cp.campaign_id, cp.campaign_name)
            .order_by(cp.campaign_name).all())


from security.deps import dm_only_sceneplay_enabled, sceneplay_dm_gate  # noqa: E402,F401
