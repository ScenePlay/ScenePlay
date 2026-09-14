"""What background modules used to take the Flask app for: a DB session
scope (`with app.app_context():` lines keep working through the alias),
filesystem roots, the secret, a URL builder and a logger."""
import logging
from contextlib import nullcontext

import core.config as config
import core.db as _db


class AppContext:
    root_path = config.ROOT
    static_dir = config.STATIC_DIR
    uploads_dir = config.UPLOADS_DIR
    instance_path = config.INSTANCE_DIR
    secret_key = config.SECRET_KEY

    def app_context(self):
        return _db.session_scope()

    def test_request_context(self):
        return nullcontext()

    def static_url(self, filename, external=False):
        import core.urls as urls
        return urls.static_url(filename, external=external)

    @property
    def logger(self):
        return logging.getLogger('sceneplay')

    # Flask duck-typing used by a few call sites
    def _get_current_object(self):
        return self


ctx = AppContext()
