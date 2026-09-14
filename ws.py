"""Production entry point (name kept: the watchdog, uninstall.sh pkill patterns
and startApp.sh/.bat all reference ws.py).

  python ws.py            production: workers forked, then uvicorn on :8086
  python ws.py --dev      uvicorn --reload, no workers (SP_WORKERS=0)
  python ws.py --no-workers
"""
import os
import sys

# Workers use repo-relative paths (./mpv.sh, processMedia/, effects/*.mp3).
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    dev = '--dev' in argv or '-flask' in argv
    no_workers = '--no-workers' in argv
    if dev:
        os.environ['SP_DEV'] = '1'
        os.environ['SP_WORKERS'] = '0'
    if no_workers:
        os.environ['SP_WORKERS'] = '0'

    import core.config as config
    import core.boot as boot
    import core.db_migrate as db_migrate

    if not dev:
        boot.install_reaper()
    boot.refuse_if_running(config.PORT)
    boot.warn_missing_tools()
    db_migrate.sync_schema()
    db_migrate.seed()
    boot.ensure_upload_dirs()
    boot.seed_appsettings()

    if not config.WORKERS:
        print('\n' + '=' * 72 + '\n  PLAYERS OFF: this instance runs without the queue/player workers\n'
              '  (SP_WORKERS=0 / --no-workers / --dev). Scenes fill the queue but nothing plays.\n'
              '  Run `python ws.py` (VS Code: the first F5 configuration) for real playback.\n' + '=' * 72 + '\n', flush=True)
    if config.WORKERS:
        import core.db as _db
        _db.engine.dispose()          # no pooled sqlite handles may cross fork
        boot.start_workers()

    import uvicorn
    if dev:
        uvicorn.run('app:app', host=config.HOST, port=config.PORT, reload=True,
                    reload_dirs=[config.ROOT],
                    reload_excludes=['static/*', 'web/*', '*.db*', 'backups/*', 'tests/*'],
                    ws='none')
    else:
        from app import app
        uvicorn.run(app, host=config.HOST, port=config.PORT, workers=1, ws='none',
                    access_log=False, log_level='info')


if __name__ == '__main__':
    main()
