"""Alembic environment — standalone (no Flask). The URL comes from the
alembic Config (db_migrate sets it); an already-open connection may be passed
via config.attributes['connection']. Autogenerate is deliberately unsupported
(target_metadata=None): most tables are raw SQL with no model."""
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

config = context.config

# disable_existing_loggers=False: upgrade() runs at every app startup — the
# alembic logging config must not silence loggers the app already created.
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
logger = logging.getLogger('alembic.env')


def run_migrations_offline():
    url = config.get_main_option('sqlalchemy.url')
    context.configure(url=url, target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = config.attributes.get('connection')
    if connectable is None:
        engine = create_engine(config.get_main_option('sqlalchemy.url'))
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=None)
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()
    else:
        context.configure(connection=connectable, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
