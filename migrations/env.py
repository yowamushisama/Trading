from __future__ import annotations

import os
import urllib.parse
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from btc_bot.storage.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load DATABASE_URL from env, normalise driver and URL-decode password chars
database_url = os.environ.get("DATABASE_URL", "")
if database_url:
    database_url = database_url.replace("postgresql+psycopg://", "postgresql+psycopg2://")
    database_url = urllib.parse.unquote(database_url)
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
