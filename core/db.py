"""SQLAlchemy 2.0 shim that keeps the Flask-SQLAlchemy surface the models and
the ported route code use: `db.Model`, `db.Column`, `db.session`,
`Model.query`, `Query.get_or_404`, `db.create_all()`.

Session scoping: request handlers run in the threadpool while the middleware
that ends the scope runs on the event loop, so the scope key is a per-request
ContextVar token (anyio copies contextvars into worker threads). Outside a
request (integration threads, timers, Windows worker threads) the scope
falls back to the thread ident — what `app.app_context()` gave those threads.
"""
import threading
from contextlib import contextmanager
from contextvars import ContextVar

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.orm import DeclarativeBase, declared_attr, scoped_session, sessionmaker

import core.config as config


class Base(DeclarativeBase):
    # Flask-SQLAlchemy derived table names from the class name; every model
    # here that relies on that has an all-lowercase class name, so the
    # equivalent default is simply the class name.
    @declared_attr.directive
    def __tablename__(cls):
        return cls.__name__.lower()


class _NotFound(Exception):
    """Raised by get_or_404 / first_or_404; app.py maps it to HTTP 404."""


class Query(orm.Query):
    def get_or_404(self, ident, description=None):
        obj = self.get(ident)
        if obj is None:
            raise _NotFound(description or 'not found')
        return obj

    def first_or_404(self, description=None):
        obj = self.first()
        if obj is None:
            raise _NotFound(description or 'not found')
        return obj


def _make_engine(path):
    return sa.create_engine(
        'sqlite:///' + path,
        connect_args={'timeout': 15, 'check_same_thread': False},
        pool_pre_ping=False,
    )


engine = _make_engine(config.DB_PATH)

_request_scope: ContextVar = ContextVar('sp_request_scope', default=None)


def _scopefunc():
    tok = _request_scope.get()
    return tok if tok is not None else threading.get_ident()


SessionLocal = sessionmaker(bind=engine, query_cls=Query, autoflush=True, expire_on_commit=True)
session = scoped_session(SessionLocal, scopefunc=_scopefunc)
Base.query = session.query_property(Query)


class _DB:
    """The `db` facade: models and routes already spell everything as db.X."""
    Model = Base
    session = session
    Query = Query
    metadata = Base.metadata
    relationship = staticmethod(orm.relationship)
    backref = staticmethod(orm.backref)

    @property
    def engine(self):
        return engine

    def create_all(self, bind=None):
        Base.metadata.create_all(bind or engine)

    def drop_all(self, bind=None):
        Base.metadata.drop_all(bind or engine)

    def __getattr__(self, name):
        # Column, Integer, Text, ForeignKey, func, or_, and_, text, ...
        return getattr(sa, name)


db = _DB()


def begin_request_scope():
    """Middleware: start a fresh session scope for this request."""
    return _request_scope.set(object())


def end_request_scope(token):
    try:
        try:
            sess = session()
            if sess.in_transaction():
                sess.rollback()
        except Exception:
            pass
        session.remove()
    finally:
        _request_scope.reset(token)


@contextmanager
def session_scope():
    """`with db.session_scope():` — replaces `with app.app_context():` for
    background threads: whatever the thread did is cleaned up on exit."""
    try:
        yield session
    finally:
        session.remove()


def bind_path(path):
    """Rebind the engine to another sqlite file (tests, restore-replace) and
    keep the legacy module-level path aliases in step."""
    global engine
    session.remove()
    engine.dispose()
    engine = _make_engine(path)
    session.configure(bind=engine)
    config.DB_PATH = path
    import sys
    ext = sys.modules.get('extensions')
    if ext is not None:
        ext.databaseDir = path
        ext.database = path
    sq = sys.modules.get('sql')
    if sq is not None:
        sq.database = path
    return engine
