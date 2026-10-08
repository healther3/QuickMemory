"""Explicit SQLite setup. Importing this module never creates a database."""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import Engine, URL, create_engine, event
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models import Base, ErrorType, Settings
from backend.launcher import database_path


DEFAULT_ERROR_TYPES = ("遗漏要点", "概念错误", "概念混淆", "表述不精确")
DEFAULT_DB_PATH = database_path()


def make_engine(db_path: str | Path | None = None) -> Engine:
    """Build an engine for a local path, QUICKMEMORY_DB, or the project data folder.

    ``:memory:`` is available for tests. Its shared connection also supports
    FastAPI's worker threads, while on-disk databases use separate connections.
    """
    selected_path = str(db_path if db_path is not None else os.environ.get("QUICKMEMORY_DB", DEFAULT_DB_PATH))
    memory_database = selected_path == ":memory:"
    if not memory_database:
        path = Path(selected_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        selected_path = str(path)

    engine = create_engine(
        URL.create("sqlite+pysqlite", database=selected_path),
        connect_args={"check_same_thread": False, "timeout": 5.0},
        **({"poolclass": StaticPool} if memory_database else {}),
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        # Let SQLAlchemy issue BEGIN explicitly. The sqlite3 legacy default can
        # otherwise commit a first SAVEPOINT independently of Session.rollback().
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA journal_mode = WAL")
        finally:
            cursor.close()

    @event.listens_for(engine, "begin")
    def begin_sqlite_transaction(connection) -> None:
        connection.exec_driver_sql("BEGIN")

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


def init_db(engine: Engine) -> None:
    """Create tables and first-run settings/error types; never seed any cards.

    Defaults are added only when creating the singleton settings row, preserving
    edits and deletions to the user's error-type vocabulary on subsequent runs.
    """
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        created = connection.execute(insert(Settings).values(id=1).on_conflict_do_nothing(index_elements=["id"]))
        if created.rowcount:
            connection.execute(
                insert(ErrorType)
                .values([{"name": name} for name in DEFAULT_ERROR_TYPES])
                .on_conflict_do_nothing(index_elements=["name"])
            )
