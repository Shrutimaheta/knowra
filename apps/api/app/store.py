"""Transactional SQLAlchemy storage for SQLite development and PostgreSQL deployment."""

import os
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]


def database_url():
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit.replace("postgres://", "postgresql+psycopg://", 1).replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    path = Path(os.getenv("KNOWRA_DB", "data/knowra.db")).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + path.as_posix()


@lru_cache(maxsize=16)
def engine_for(url):
    options = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("sqlite:"):
        options.update(
            connect_args={"timeout": 30, "check_same_thread": False}, poolclass=NullPool
        )
    engine = create_engine(url, **options)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    return engine


def engine():
    return engine_for(database_url())


class Connection:
    """Compatibility for parameterized repositories; values never enter SQL text."""

    def __init__(self, connection):
        self.raw = connection

    def execute(self, sql, parameters=()):
        if not isinstance(parameters, dict):
            parts = sql.split("?")
            if len(parts) - 1 != len(parameters):
                raise ValueError("SQL placeholder count does not match values")
            sql = parts[0] + "".join(
                f":p{i}" + part for i, part in enumerate(parts[1:])
            )
            parameters = {f"p{i}": value for i, value in enumerate(parameters)}
        result = self.raw.execute(text(sql), parameters)
        return result.mappings() if result.returns_rows else result


@contextmanager
def db():
    with engine().begin() as connection:
        yield Connection(connection)


def migration_config():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    return config


def initialize():
    """Upgrade new and legacy databases without dropping existing identities or data."""
    config = migration_config()
    direct = os.getenv("DATABASE_URL_UNPOOLED")
    migration_engine = engine_for(direct.replace("postgresql://", "postgresql+psycopg://", 1).replace("postgres://", "postgresql+psycopg://", 1)) if direct else engine()
    with migration_engine.begin() as connection:
        config.attributes["connection"] = connection
        tables = inspect(connection).get_table_names()
        if "users" in tables and "alembic_version" not in tables:
            command.stamp(config, "0001")
        command.upgrade(config, "head")
