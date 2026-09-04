"""Database engine and session management."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


def normalize_database_url(url: str) -> str:
    """Select psycopg 3 for provider-style PostgreSQL connection URLs."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def escape_alembic_url(url: str) -> str:
    """Escape percent signs before storing a URL in Alembic's ConfigParser."""
    return url.replace("%", "%%")


def create_engine_for_url(url: str) -> Engine:
    """Build an Engine; enable WAL + foreign keys for file-backed SQLite.

    In-memory SQLite uses a StaticPool so a single shared connection persists
    across sessions (otherwise each session would get a fresh, empty database).
    """
    url = normalize_database_url(url)
    is_sqlite = url.startswith("sqlite")
    is_memory = is_sqlite and ":memory:" in url

    if is_memory:
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    elif is_sqlite:
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url)

    if is_sqlite and not is_memory:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Provide a transactional scope; commit on success, rollback on error.

    Catches BaseException so that KeyboardInterrupt / SystemExit also trigger an
    explicit rollback before propagating.
    """
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
