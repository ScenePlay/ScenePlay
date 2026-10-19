"""Utilities page (routes/Utilities.py core): page data, the actions that used
to be form submits, software update, backups, download queue, chimes."""
import os
import subprocess
import threading

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import FileResponse

import ops.backup_restore as backup_restore
import core.config as config
from core.procutil import uptime_info
import core.events as events
from core.db import db
from extensions import currentvolume
from models.scenes import tblscenes as sc
from routers._util import form_or_json, json_body
from security.deps import (ApiError, dm_only_sceneplay_enabled, get_current_user, require_dm,
                           require_dm_or_signed, sceneplay_dm_gate, signed_url)
from sql import (LIGHTS_OFF_ON_SCENE_END, appsettingGet, appsettingGetKeepMusicPlaying, appsettingSet,
                 backfill_video_ids, download_stats, failed_downloads, lights_off_on_scene_end_enabled,
                 scan_missing_media)

router = APIRouter(dependencies=[Depends(sceneplay_dm_gate)])
open_router = APIRouter()


def restart_computer(sudo_password=None):
    """Reboot the box: shutdown.exe on Windows, restartComputer.sh on Linux."""
    if os.name == 'nt':
        subprocess.Popen(['shutdown', '/r', '/t', '3'], shell=False)
        return
    if sudo_password:
        subprocess.run(['sudo', '-S', '-p', '', 'shutdown', '-r', 'now'],
                       input=sudo_password + '\n', text=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        return
    subprocess.Popen(['bash', os.path.join(config.ROOT, 'restartComputer.sh')], shell=False)


def remove_list_param(input_str):
    if '&list' in input_str:
        return input_str.split('&list')[0]
    return input_str


def _safe_backup_name(name):
    return ('/' not in name and '\\' not in name
            and name.startswith('sceneplay-') and name.endswith('.zip'))


# ── page data ─────────────────────────────────────────────────────────────────

@router.get('/api/v1/utilities')
def page(user=Depends(get_current_user)):
    import integrations.gemini as gemini
    import integrations.runware as runware
    scenes = sc.query.with_entities(sc.scene_ID, sc.sceneName).order_by(sc.sceneName).all()
    backups = [{'name': b['name'], 'created': b['created'], 'size': b['size'],
                'url': signed_url(f"/backups/{b['name']}", 3600)} for b in backup_restore.list_backups()]
    is_dm = user is not None and user.is_dm()
    try:
        volume = currentvolume()
    except Exception:
        volume = 0
    return {
        'volume': volume,
        'scenes': [[0, 'None']] + [[s[0], s[1]] for s in scenes],
        'keep_music': bool(appsettingGetKeepMusicPlaying()),
        'backups': backups,
        'backup_auto': str(appsettingGet('backup_auto', '0') or '0') == '1',
        'lights_off_on_end': lights_off_on_scene_end_enabled(),
        'media_roots': appsettingGet('media_search_roots', '') or '',
        'dm_only_sceneplay': dm_only_sceneplay_enabled(),
        'is_dm': is_dm,
        'uptime': uptime_info(),
        'gemini_configured': gemini.configured(),
        'gemini_key_source': gemini.key_source(),
        'gemini_models': {m: gemini.resolve_model(m) for m in ('text', 'image', 'video')},
        'gemini_choices': {'text': list(gemini.TEXT_MODELS), 'image': list(gemini.IMAGE_MODELS),
                           'video': list(gemini.VIDEO_MODELS)},
        'runware_configured': runware.configured(),
        'runware_key_source': runware.key_source(),
        'runware_model': runware.resolve_model(),
        'image_provider': appsettingGet('image_provider', 'gemini') or 'gemini',
        'text_provider': appsettingGet('text_provider', 'gemini') or 'gemini',
        'runware_text_model': runware.resolve_text_model(),
    }


# ── the old form actions, one JSON endpoint each ──────────────────────────────

@router.post('/api/v1/youtube/import')
def youtube_import(data: dict = Depends(form_or_json)):
    from routers.public import addMediaToYT_que
    url = (data.get('URLLink') or data.get('url') or '').strip()
    if not url:
        raise ApiError(400, 'A YouTube URL is required.')
    flname = (data.get('FileName') or data.get('flname') or '').strip()
    scene_ID = data.get('Scene') or data.get('scene_ID') or 0
    mediaType = data.get('Media') or data.get('mediaType') or 'mp3'
    addMediaToYT_que(url, flname, mediaType, scene_ID)
    events.emit('downloads', {'reason': 'enqueued'})
    return {'ok': True, 'message': 'Queued for download.'}


@router.post('/api/v1/library/backfill-metadata')
def backfill_metadata():
    summary = backfill_video_ids()
    return {'ok': True, 'summary': summary,
            'message': f"Backfill: tagged {summary['tagged']}, duplicates skipped "
                       f"{summary['duplicates_skipped']}, unparseable {summary['unparseable']}."}


@router.post('/api/v1/library/scan-media')
def scan_media():
    summary = scan_missing_media()
    if summary['music'] or summary['video']:
        msg = (f"Scan: re-queued {summary['music']} songs and {summary['video']} videos "
               f"for download — they are downloading now.")
    else:
        msg = "Scan: all downloadable media files are present on disk."
    events.emit('downloads', None)
    return {'ok': True, 'summary': summary, 'message': msg}


@router.post('/api/v1/backup/run')
def backup_run():
    path = backup_restore.create_backup(label='manual')
    return {'ok': True, 'name': os.path.basename(path),
            'message': f"Backup created: {os.path.basename(path)}"}


@router.post('/api/v1/utilities/settings')
def settings(data: dict = Depends(json_body), user=Depends(get_current_user)):
    """One endpoint for the small toggles: media_search_roots, backup_auto,
    lights_off_on_scene_end, dm_only_sceneplay (DM only)."""
    msgs = []
    if 'media_search_roots' in data:
        roots = (data.get('media_search_roots') or '').strip()
        appsettingSet('media_search_roots', roots)
        missing = [p.strip() for p in roots.split(';') if p.strip() and not os.path.isdir(p.strip())]
        m = 'Media search folders saved.'
        if missing:
            m += f" Warning — not found on this machine: {', '.join(missing)}"
        msgs.append(m)
    if 'backup_auto' in data:
        enable = bool(data['backup_auto'])
        appsettingSet('backup_auto', 1 if enable else 0, 'int')
        msgs.append(f"Nightly backup {'enabled' if enable else 'disabled'}.")
    if 'lights_off_on_scene_end' in data:
        enable = bool(data['lights_off_on_scene_end'])
        appsettingSet(LIGHTS_OFF_ON_SCENE_END, '1' if enable else '0')
        msgs.append("Lights will turn off when a scene's media finishes." if enable
                    else "Lights stay on after a scene's media finishes (until the next scene or All Stop).")
    if 'dm_only_sceneplay' in data:
        if not (user is not None and user.is_dm()):
            raise ApiError(403, 'Changing access control requires a DM login.', code='dm_required')
        enable = bool(data['dm_only_sceneplay'])
        appsettingSet('DMOnlyScenePlay', 1 if enable else 0, 'int')
        msgs.append('ScenePlay controls and tables are now DM-only.' if enable
                    else 'ScenePlay controls and tables are open to everyone on the network.')
    return {'ok': True, 'message': ' '.join(msgs)}


@router.post('/api/v1/utilities/ai-settings')
def ai_settings(data: dict = Depends(json_body), user=Depends(require_dm)):
    import integrations.gemini as gemini
    import integrations.runware as runware
    msgs = []
    if data.get('gemini_clear_key'):
        gemini.clear_api_key()
        msgs.append('Gemini API key removed.')
    else:
        key = (data.get('gemini_api_key') or '').strip()
        if key:
            gemini.save_api_key(key)
            msgs.append('Gemini API key saved (stored locally in instance/, never in the database or git).')
    for modality in ('text', 'image', 'video'):
        chosen = data.get(f'gemini_model_{modality}', '')
        if chosen in gemini._ALLOWED[modality]:
            appsettingSet(f'gemini_model_{modality}', chosen)
    if data.get('runware_clear_key'):
        runware.clear_api_key()
        msgs.append('Runware API key removed.')
    else:
        rkey = (data.get('runware_api_key') or '').strip()
        if rkey:
            runware.save_api_key(rkey)
            msgs.append('Runware API key saved (stored locally in instance/, never in the database or git).')
    rmodel = (data.get('runware_model') or '').strip()
    if rmodel and ':' in rmodel:
        ok, why = runware.validate_image_model(rmodel)
        if ok:
            appsettingSet('runware_model', rmodel)
        else:
            msgs.append(why)
    provider = data.get('image_provider', 'gemini')
    appsettingSet('image_provider', 'runware' if provider == 'runware' else 'gemini')
    rtext = (data.get('runware_text_model') or '').strip()
    if rtext:
        slug, why = runware.normalize_text_model(rtext)
        if slug:
            appsettingSet('runware_text_model', slug)
            if slug != rtext:
                msgs.append(f'Layout model saved as "{slug}" (the chat API uses slug ids; converted automatically).')
        else:
            msgs.append(why)
    tprov = data.get('text_provider', 'gemini')
    appsettingSet('text_provider', 'runware' if tprov == 'runware' else 'gemini')
    msgs.append('AI settings saved.')
    return {'ok': True, 'message': ' '.join(msgs)}


@router.post('/api/v1/system/reset-ytdlp')
def reset_ytdlp():
    import media.ytdlp_source as ytdlp_source
    if ytdlp_source.reset():
        return {'ok': True, 'message': 'yt-dlp reset: checkout deleted and re-cloned fresh from GitHub.'}
    return {'ok': False, 'message': 'yt-dlp reset: checkout deleted, but the re-clone failed '
                                    '(network/git problem?) — downloads fall back to the '
                                    'pip-installed copy until the next successful refresh.'}


@router.post('/api/v1/system/restart-computer')
def restart_computer_endpoint(data: dict = Depends(json_body), user=Depends(get_current_user)):
    from models.user import tblUsers
    if not (user is not None and user.is_dm()):
        if tblUsers.query.first() is None:
            raise ApiError(403, 'Restarting the computer requires a DM account — create one first.',
                           code='setup_needed')
        raise ApiError(403, 'Restarting the computer requires a DM login.', code='dm_required')
    threading.Timer(3.0, restart_computer, kwargs={'sudo_password': data.get('sudo_password') or None}).start()
    return {'ok': True, 'message': 'Restarting the computer…', 'redirect': '/restarting.html'}


@router.post('/api/v1/system/restart')
def restart_app(user=Depends(require_dm)):
    """Post-update restart: the SPA shows /restarting.html, then the watchdog
    (Linux) or the detached helper (Windows) brings the app back."""
    import ops.app_update as app_update
    app_update.restart_app(3.0)
    return {'ok': True, 'redirect': '/restarting.html'}


@router.get('/utilities/restart-app')
def utilities_restart_app(user=Depends(require_dm)):
    import ops.app_update as app_update
    app_update.restart_app(3.0)
    return FileResponse(os.path.join(config.WEB_DIR, 'restarting.html'), media_type='text/html')


# ── software update ───────────────────────────────────────────────────────────

@router.get('/api/update/check')
def update_check():
    import ops.app_update as app_update
    return app_update.check_updates()


@router.post('/api/update/run')
def update_run(data: dict = Depends(json_body), user=Depends(get_current_user)):
    if not (user is not None and user.is_dm()):
        raise ApiError(403, 'DM login required.', code='dm_required')
    import ops.app_update as app_update
    return app_update.run_update(sudo_password=data.get('sudo_password') or None)


# ── backups ───────────────────────────────────────────────────────────────────

@open_router.get('/backups/{name}')
def backup_download(name: str, _=Depends(require_dm_or_signed)):
    if not _safe_backup_name(name):
        raise ApiError(404, 'not found')
    path = os.path.join(backup_restore.BACKUP_DIR, name)
    if not os.path.isfile(path):
        raise ApiError(404, 'not found')
    return FileResponse(path, media_type='application/zip', filename=name)


@router.post('/api/backupdelete')
def backup_delete(data: dict = Depends(json_body)):
    name = data.get('name', '')
    if not _safe_backup_name(name):
        raise ApiError(400, 'bad backup name')
    try:
        os.remove(os.path.join(backup_restore.BACKUP_DIR, name))
    except OSError:
        raise ApiError(404, 'not found')
    return {'deleted': name}


@router.post('/backup/import')
def backup_import(request: Request, backupFile: UploadFile = File(None), user=Depends(get_current_user)):
    """Restore an uploaded archive. mode=replace swaps the whole database
    (safety snapshot first); mode=merge folds campaigns/scenes/media in with
    dedup. Either way missing media re-queues for download."""
    import anyio
    form = anyio.from_thread.run(request.form)
    mode = form.get('mode', 'merge')
    include_uploads = not form.get('db_only')
    if not backupFile or not backupFile.filename:
        raise ApiError(400, 'Import: no file selected.')
    os.makedirs(backup_restore.BACKUP_DIR, exist_ok=True)
    staged = os.path.join(backup_restore.BACKUP_DIR, '.upload.zip')
    with open(staged, 'wb') as out:
        while True:
            chunk = backupFile.file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    try:
        img_note = '' if include_uploads else ' (database only — images skipped)'
        if mode == 'replace':
            summary = backup_restore.restore_replace(staged, include_uploads=include_uploads)
            db.engine.dispose()
            msg = (f"Restored from {summary['from']} (backup of {summary['created_at']}): "
                   f"{summary['uploads_restored']} images, {summary.get('found_local', 0)} media files "
                   f"found already on this machine, {summary['requeued_downloads']} downloads "
                   f"re-queued{img_note}. Safety copy: {summary['safety_backup']}. RESTART the app now.")
        else:
            full = bool(form.get('full_merge'))
            fallback_uid = user.user_id if (full and user is not None) else None
            summary = backup_restore.restore_merge(staged, include_uploads=include_uploads,
                                                   full=full, fallback_user_id=fallback_uid)
            msg = (f"Merged from {summary['from']}: {summary['campaigns']} campaigns, "
                   f"{summary['scenes']} scenes, {summary['music']} songs, {summary['video']} videos, "
                   f"{summary['links']} scene links, {summary.get('homebrew', 0)} library entries, "
                   f"{summary['uploads_added']} images{img_note} "
                   f"({summary['skipped_legacy']} legacy rows skipped, "
                   f"{summary.get('found_local', 0)} media files found already local).")
            if full:
                msg += (f" TTRPG: {summary['characters']} characters "
                        f"({summary['characters_skipped']} kept local), "
                        f"{summary['sessions']} sessions, {summary['maps']} maps, "
                        f"{summary['session_monsters']} monsters, {summary['tokens']} tokens, "
                        f"{summary.get('floorplans', 0)} 3D floorplans, "
                        f"{summary.get('map_prompts', 0)} map prompts, "
                        f"{summary.get('obs_bindings', 0)} OBS bindings, "
                        f"{summary.get('dice_rolls', 0)} dice rolls, "
                        f"{summary.get('cron_schedules', 0)} cron schedules (imported inactive), "
                        f"{summary['notes']} notes, {summary['lighting']} lighting links.")
                if summary.get('characters_no_owner'):
                    msg += (f" WARNING: {summary['characters_no_owner']} characters were NOT "
                            f"imported — this box has no user accounts yet. Create the DM "
                            f"account (or log in) and run the merge again.")
            msg += ' New media is downloading.'
        events.emit('downloads', None)
        return {'ok': True, 'message': msg, 'summary': summary}
    except ValueError as e:
        raise ApiError(400, f'Import failed: {e}')
    finally:
        try:
            os.remove(staged)
        except OSError:
            pass


@open_router.api_route('/processyt', methods=['GET', 'POST'])
def processyt(data: dict = Depends(form_or_json)):
    """Legacy intake (kept open like the Flask version: the extension's older
    builds posted here)."""
    from media.ytProcess import yt_process
    url = remove_list_param(data.get('URLLink') or '')
    flname = data.get('FileName') or ''
    yt_process(url, flname)
    return {'ok': True}


# ── download queue card ───────────────────────────────────────────────────────

def downloads_payload():
    return {'ok': True, 'stats': download_stats(), 'failed': failed_downloads()}


@router.get('/api/downloads/status')
def downloads_status():
    return downloads_payload()


@router.post('/api/downloads/retry')
def downloads_retry(data: dict = Depends(json_body)):
    from sql import retry_all_failed, retry_download
    if data.get('all'):
        n = retry_all_failed(include_unavailable=bool(data.get('include_unavailable')))
        events.emit('downloads', None)
        return {'ok': True, 'requeued': n}
    try:
        pk = int(data.get('id') or 0)
    except (TypeError, ValueError):
        pk = 0
    kind = data.get('media_type')
    if not pk or kind not in ('music', 'video'):
        raise ApiError(400, 'media_type and id required')
    changed = retry_download(kind, pk)
    events.emit('downloads', None)
    return {'ok': True, 'requeued': 1 if changed else 0}


@router.post('/api/downloads/delete')
def downloads_delete(data: dict = Depends(json_body)):
    from sql import delete_all_failed, delete_failed_download
    if data.get('all'):
        n = delete_all_failed(include_unavailable=bool(data.get('include_unavailable')))
        events.emit('downloads', None)
        return {'ok': True, 'deleted': n}
    try:
        pk = int(data.get('id') or 0)
    except (TypeError, ValueError):
        pk = 0
    kind = data.get('media_type')
    if not pk or kind not in ('music', 'video'):
        raise ApiError(400, 'media_type and id required')
    if not delete_failed_download(kind, pk):
        raise ApiError(400, 'Only failed or unavailable downloads can be removed here.')
    events.emit('downloads', None)
    return {'ok': True, 'deleted': 1}


# ── chimes ────────────────────────────────────────────────────────────────────

def _chimes_payload():
    import media.chimes as chimes
    d = chimes.effects_dir()
    return {'ok': True, 'events': chimes.config(appsettingGet, d), 'sounds': chimes.available_sounds(d)}


@router.get('/api/chimes')
def chimes_get():
    return _chimes_payload()


@router.post('/api/chimes')
def chimes_set(data: dict = Depends(json_body)):
    import media.chimes as chimes
    ok = chimes.save(appsettingGet, appsettingSet, chimes.effects_dir(), data.get('key'),
                     enabled=(bool(data['enabled']) if 'enabled' in data else None),
                     file=(data.get('file') if 'file' in data else None))
    if not ok:
        raise ApiError(400, 'Unknown chime or sound file.')
    return _chimes_payload()


@open_router.get('/chimes/sound/{name}')
def chime_sound(name: str):
    import media.chimes as chimes
    if not chimes.safe_sound_name(name):
        raise ApiError(404, 'not found')
    path = os.path.join(chimes.effects_dir(), name)
    if not os.path.isfile(path):
        raise ApiError(404, 'not found')
    return FileResponse(path)


@router.post('/api/chimes/upload')
def chimes_upload(sound: UploadFile = File(None), key: str = None):
    import media.chimes as chimes
    if not sound or not sound.filename:
        raise ApiError(400, 'No file.')
    name = os.path.basename(sound.filename).strip().replace('/', '_')
    if not chimes.safe_sound_name(name):
        raise ApiError(400, 'Use a plain .mp3, .wav or .ogg filename.')
    raw = sound.file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise ApiError(400, 'Keep chimes under 2 MB.')
    d = chimes.effects_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), 'wb') as out:
        out.write(raw)
    if key:
        chimes.save(appsettingGet, appsettingSet, d, key, file=name)
    return _chimes_payload()


events.register_derived('downloads', downloads_payload, 2.0)


# ═════════════════════════════════════════════════════════════════════════════
# Utilities sub-pages (P2): downloads (assets), genres, artists, smart scenes,
# organize (ported from routes/Utilities.py 437-930)
# ═════════════════════════════════════════════════════════════════════════════
import json as _json                                    # noqa: E402
from fastapi.responses import RedirectResponse, StreamingResponse   # noqa: E402


def _uploads_dir():
    return config.UPLOADS_DIR


@router.get('/api/v1/library/assets')
def assets_page():
    import media.assets_inventory as inv
    from extensions import database
    music = inv.media_rows(database, 'music')
    video = inv.media_rows(database, 'video')
    pics = inv.picture_rows(database, _uploads_dir())
    for kind, rows in (('music', music), ('video', video)):
        for r in rows:
            r['download_url'] = signed_url(f"/assets/download/{kind}/{r['id']}", 3600) if r['exists'] else ''
    for r in pics:
        r['download_url'] = signed_url(f"/assets/download/picture/{r['folder']}/{r['file']}", 3600)
    return {'music': music, 'video': video, 'pictures': pics,
            'totals': {'music': inv.totals(music), 'video': inv.totals(video), 'pictures': inv.totals(pics)},
            'zip_urls': {k: signed_url(f'/assets/zip/{k}', 3600) for k in ('music', 'video', 'pictures')}}


def _media_row(kind, media_id):
    import media.assets_inventory as inv
    from extensions import database
    if kind not in inv.MEDIA_KINDS:
        raise ApiError(404, 'not found')
    for r in inv.media_rows(database, kind):
        if r['id'] == media_id:
            return r
    raise ApiError(404, 'not found')


@open_router.get('/assets/download/{kind}/{media_id}')
def asset_download_media(kind: str, media_id: int, _=Depends(require_dm_or_signed)):
    import media.assets_inventory as inv
    r = _media_row(kind, media_id)
    if not r['exists']:
        raise ApiError(404, 'not found')
    return FileResponse(os.path.join(r['dir'], r['file']), filename=r['file'])


@open_router.get('/assets/download/picture/{folder}/{name}')
def asset_download_picture(folder: str, name: str, _=Depends(require_dm_or_signed)):
    import media.assets_inventory as inv
    if not inv.safe_picture_ref(folder, name):
        raise ApiError(404, 'not found')
    path = os.path.join(_uploads_dir(), folder, name)
    if not os.path.isfile(path):
        raise ApiError(404, 'not found')
    return FileResponse(path, filename=name)


@open_router.get('/assets/zip/{kind}')
def asset_zip(kind: str, _=Depends(require_dm_or_signed)):
    """One zip per category, streamed — never assembled in memory or on disk."""
    import media.assets_inventory as inv
    from extensions import database
    if kind in inv.MEDIA_KINDS:
        entries = [(inv.arc_name(r, kind), r['path']) for r in inv.media_rows(database, kind) if r['exists']]
    elif kind == 'pictures':
        entries = [(f"{r['folder']}/{r['file']}", r['path']) for r in inv.picture_rows(database, _uploads_dir())]
    else:
        raise ApiError(404, 'not found')
    if not entries:
        raise ApiError(404, 'nothing to zip')
    return StreamingResponse(inv.zip_stream(entries), media_type='application/zip',
                             headers={'Content-Disposition': f'attachment; filename="sceneplay-{kind}.zip"'})


@router.get('/utilities/assets/api/list')
def assets_api_list():
    """Picker feed: every picture upload and every library / uploaded video."""
    import media.assets_inventory as inv
    from extensions import database
    items = []
    for r in inv.picture_rows(database, _uploads_dir()):
        ext = r['file'].rsplit('.', 1)[-1].lower() if '.' in r['file'] else ''
        kind = 'video' if ext in ('mp4', 'webm', 'ogv') else 'image'
        items.append({'type': kind, 'source': 'upload', 'folder': r['folder'],
                      'folder_label': r['folder_label'], 'file': r['file'], 'ext': ext,
                      'name': r['used_by'] or r['file'], 'sub': r['folder_label'],
                      'url': f"/static/uploads/{r['folder']}/{r['file']}",
                      'size_h': r['size_h']})
    for r in inv.media_rows(database, 'video'):
        if not r['exists']:
            continue
        ext = r['file'].rsplit('.', 1)[-1].lower() if '.' in r['file'] else ''
        items.append({'type': 'video', 'source': 'library', 'id': r['id'], 'file': r['file'],
                      'ext': ext, 'name': r['name'],
                      'sub': 'Video library' + (f" · {r['duration_h']}" if r['duration_h'] else ''),
                      'url': f"/assets/media/video/{r['id']}.{ext}",
                      'thumb': _video_thumb(r['id']), 'size_h': r['size_h']})
    return {'ok': True, 'items': items}


def _video_thumb(media_id):
    import sqlite3
    from extensions import database
    conn = sqlite3.connect(database)
    try:
        row = conn.execute("SELECT thumbnail FROM tblMediaMetadata WHERE media_type='video' "
                           "AND media_id=? AND COALESCE(active,1)=1", (media_id,)).fetchone()
    finally:
        conn.close()
    return (row[0] or '') if row else ''


# ── genres ────────────────────────────────────────────────────────────────────

@router.get('/api/v1/library/genres')
def genres_page():
    import ttrpg.genre_suggest as gs
    from extensions import database
    rows = gs.suggest(database, appsettingGet)
    names = gs.genre_names(database)
    proposed = sorted({r['suggested'] for r in rows if r['suggested']} |
                      {r['alt'] for r in rows if r['alt']} | set(names), key=str.lower)
    counts = {k: sum(1 for r in rows if r['confidence'] == k) for k in ('scene', 'tags', 'conflict', 'none')}
    return {'rows': rows, 'genres': proposed, 'counts': counts, 'scene_map': gs.scene_map(appsettingGet)}


@router.post('/api/genres/apply')
def genres_apply(data: dict = Depends(json_body)):
    import ttrpg.genre_suggest as gs
    from extensions import database
    items = data.get('items') or []
    if not isinstance(items, list):
        raise ApiError(400, 'items must be a list')
    return {'ok': True, **gs.apply(database, items)}


@router.post('/api/genres/scene-map')
def genres_scene_map(data: dict = Depends(json_body)):
    m = data.get('map')
    if not isinstance(m, dict):
        raise ApiError(400, 'map must be an object')
    appsettingSet('genre_scene_map', _json.dumps({str(k): str(v or '') for k, v in m.items()}))
    return {'ok': True}


# ── artists ───────────────────────────────────────────────────────────────────

@router.get('/api/v1/library/artists')
def artists_page():
    import media.media_facets as mf
    from extensions import database
    rows = mf.suggest_artists(database)
    counts = {k: sum(1 for r in rows if r['confidence'] == k) for k in ('exact', 'high', 'medium', 'low', 'none')}
    return {'rows': rows, 'counts': counts, 'kinds': list(mf.KINDS)}


@router.post('/api/artists/build')
def artists_build(data: dict = Depends(json_body)):
    import media.media_facets as mf
    from extensions import database
    want = {'exact', 'high'} | ({'medium'} if data.get('include_medium') else set())
    rows = mf.suggest_artists(database)
    picked = [{'media_type': r['media_type'], 'id': r['id'], 'artist': r['artist']}
              for r in rows if r['confidence'] in want and r['artist']]
    updated = mf.apply_artists(database, picked)
    left = {k: sum(1 for r in rows if r['confidence'] == k and k not in want) for k in ('medium', 'low', 'none')}
    return {'ok': True, 'updated': updated, 'left': left}


@router.post('/api/artists/apply')
def artists_apply(data: dict = Depends(json_body)):
    import media.media_facets as mf
    from extensions import database
    items = data.get('items') or []
    if not isinstance(items, list):
        raise ApiError(400, 'items must be a list')
    return {'ok': True, 'updated': mf.apply_artists(database, items)}


# ── smart scenes ──────────────────────────────────────────────────────────────

@router.get('/api/v1/library/smart-scenes')
def smart_scenes_page():
    import media.media_facets as media_facets
    import media.smart_scenes as ss
    from extensions import database
    from models.campaigns import tblcampaigns as cp
    from models.scenes import tblscenes as sc
    campaigns = cp.query.with_entities(cp.campaign_id, cp.campaign_name).order_by(cp.campaign_name).all()
    scenes = sc.query.with_entities(sc.scene_ID, sc.sceneName, sc.campaign_id).order_by(sc.sceneName).all()
    return {'options': ss.facet_options(database), 'rules': ss.list_rules(database),
            'campaigns': [list(c) for c in campaigns], 'scenes': [list(s) for s in scenes],
            'kinds': list(media_facets.KINDS)}


@router.get('/api/smart-scenes/facets')
def smart_scenes_facets():
    import media.smart_scenes as ss
    from extensions import database
    from models.campaigns import tblcampaigns as cp
    return {'ok': True, 'options': ss.facet_options(database),
            'campaigns': [{'id': c.campaign_id, 'name': c.campaign_name} for c in cp.query.order_by(cp.campaign_name)]}


@router.post('/api/smart-scenes/preview')
def smart_scenes_preview(data: dict = Depends(json_body)):
    import media.smart_scenes as ss
    from extensions import database
    rule = data.get('rule') or {}
    m = ss.match(database, rule)
    return {'ok': True, 'summary': ss.describe(rule),
            'music': [{'id': i, 'name': n} for i, n in m['music']],
            'video': [{'id': i, 'name': n} for i, n in m['video']]}


def _campaign_or_default(raw):
    from models.campaigns import tblcampaigns as cp
    try:
        cid = int(raw or 0)
    except (TypeError, ValueError):
        cid = 0
    if cid and db.session.get(cp, cid):
        return cid
    row = cp.query.filter(db.func.lower(cp.campaign_name) == 'music').first() or cp.query.order_by(cp.campaign_id).first()
    return row.campaign_id if row else 0


@router.post('/api/smart-scenes/create')
def smart_scenes_create(data: dict = Depends(json_body)):
    import media.smart_scenes as ss
    from extensions import database
    rule = data.get('rule') or {}
    try:
        if data.get('scene_id'):
            ss.set_rule(database, int(data['scene_id']), rule, bool(data.get('auto_refresh', True)))
            added = ss.refresh(database, int(data['scene_id']))
            return {'ok': True, 'scene_id': int(data['scene_id']), 'added': added}
        res = ss.create_scene(database, data.get('name'), _campaign_or_default(data.get('campaign_id')), rule,
                              bool(data.get('auto_refresh', True)))
        events.emit('scene', {'reason': 'smart-scene'})
        return {'ok': True, **res}
    except (ValueError, TypeError) as exc:
        raise ApiError(400, str(exc))


@router.post('/api/smart-scenes/from-queue')
def smart_scenes_from_queue(data: dict = Depends(json_body)):
    import media.smart_scenes as ss
    from extensions import database
    from sql import scene_queue_states
    states = scene_queue_states()
    picked = data.get('scene_ids')
    ids = ([int(x) for x in picked if str(x).lstrip('-').isdigit() and states.get(int(x)) in ('all', 'some')]
           if isinstance(picked, list) and picked else
           [sid for sid, st in states.items() if st in ('all', 'some')])
    names = [r[0] for r in db.session.execute(
        db.text("SELECT sceneName FROM tblScenes WHERE scene_ID IN :ids ORDER BY sceneName").bindparams(
            db.bindparam('ids', expanding=True)), {'ids': ids or [0]})]
    if len(names) < 2:
        raise ApiError(400, 'Queue two or more scenes first.')
    name = (data.get('name') or '').strip() or ' + '.join(names)
    try:
        res = ss.create_scene(database, name, _campaign_or_default(data.get('campaign_id')),
                              {'scenes': names, 'media': ['music', 'video']})
    except ValueError as exc:
        raise ApiError(400, str(exc))
    return {'ok': True, 'name': name, 'sources': names, **res}


@router.post('/api/smart-scenes/refresh')
def smart_scenes_refresh(data: dict = Depends(json_body)):
    import media.smart_scenes as ss
    from extensions import database
    if data.get('all'):
        return {'ok': True, 'added': ss.refresh_all(database, auto_only=False)}
    return {'ok': True, 'added': ss.refresh(database, int(data.get('scene_id') or 0))}


@router.post('/api/smart-scenes/drop')
def smart_scenes_drop(data: dict = Depends(json_body)):
    import media.smart_scenes as ss
    from extensions import database
    ss.drop_rule(database, int(data.get('scene_id') or 0))
    return {'ok': True}


@router.post('/api/smart-scenes/bulk')
def smart_scenes_bulk(data: dict = Depends(json_body)):
    import media.smart_scenes as ss
    from extensions import database
    try:
        made = ss.bulk_create(database, data.get('by'), int(data.get('min_count') or 3),
                              int(data.get('campaign_id') or 0),
                              media=tuple(data.get('media') or ss.MEDIA),
                              name_format=str(data.get('name_format') or '{value}'))
    except ValueError as exc:
        raise ApiError(400, str(exc))
    return {'ok': True, 'made': made}


# ── organize library ──────────────────────────────────────────────────────────

@router.get('/api/v1/library/organize')
def organize_page():
    from models.campaigns import tblcampaigns as cp
    campaigns = cp.query.with_entities(cp.campaign_id, cp.campaign_name).order_by(cp.campaign_name).all()
    return {'campaigns': [list(c) for c in campaigns]}


@router.post('/api/library/organize')
def organize_api(data: dict = Depends(json_body)):
    import media.library_organize as lo
    from extensions import database
    opts = data.get('options') or {}
    try:
        if data.get('dry_run', True):
            return {'ok': True, 'dry_run': True, **lo.plan(database, appsettingGet, opts)}
        return {'ok': True, 'dry_run': False, **lo.run(database, appsettingGet, opts)}
    except (ValueError, TypeError) as exc:
        raise ApiError(400, str(exc))


@open_router.get('/utilities/library')
def library_page():
    return RedirectResponse('/utilities/organize', status_code=302)
