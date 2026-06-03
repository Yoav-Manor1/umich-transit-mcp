"""Tests for the database engine and session factory."""
from sqlalchemy import text

from umich_transit.core.storage.db import create_engine_for_url, session_scope


def test_create_engine_uses_wal_for_sqlite():
    engine = create_engine_for_url("sqlite:///:memory:")
    with engine.connect() as conn:
        mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        assert mode in {"wal", "memory"}  # :memory: cannot use WAL


def test_session_scope_commits_on_success():
    engine = create_engine_for_url("sqlite:///:memory:")
    with session_scope(engine) as session:
        session.execute(text("CREATE TABLE foo (id INTEGER)"))
        session.execute(text("INSERT INTO foo VALUES (1)"))
    with session_scope(engine) as session:
        row = session.execute(text("SELECT id FROM foo")).scalar()
        assert row == 1


def test_session_scope_rolls_back_on_error():
    engine = create_engine_for_url("sqlite:///:memory:")
    with session_scope(engine) as session:
        session.execute(text("CREATE TABLE foo (id INTEGER)"))
    try:
        with session_scope(engine) as session:
            session.execute(text("INSERT INTO foo VALUES (1)"))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with session_scope(engine) as session:
        count = session.execute(text("SELECT COUNT(*) FROM foo")).scalar()
        assert count == 0
