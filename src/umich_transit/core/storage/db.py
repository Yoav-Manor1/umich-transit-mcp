"""Database engine and session management."""
from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

logger = structlog.get_logger(__name__)


def create_engine_for_url(url: str) -> Engine:
    """Build an Engine; enable WAL + foreign keys for file-backed SQLite.

    In-memory SQLite uses a StaticPool so a single shared connection persists
    across sessions (otherwise each session would get a fresh, empty database).
    """
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
    active_error: BaseException | None = None
    try:
        yield session
        session.commit()
    except BaseException as exc:
        active_error = exc
        try:
            session.rollback()
        except Exception as rollback_exc:
            logger.warning(
                "session_scope.rollback_failed",
                error=str(rollback_exc),
                error_type=type(rollback_exc).__name__,
                exc_info=True,
            )
        raise
    finally:
        try:
            session.close()
        except Exception as close_exc:
            logger.warning(
                "session_scope.close_failed",
                error=str(close_exc),
                error_type=type(close_exc).__name__,
                exc_info=True,
            )
            if active_error is None:
                raise
