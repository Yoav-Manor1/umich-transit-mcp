# U-Mich Transit MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python MCP server that exposes U-Mich Magic Bus arrival data to Claude, with a background poller that logs predictions and detects actual arrivals to surface empirically adjusted ETAs.

**Architecture:** Three components in one package — a shared `core/` library, a thin `mcp_server/` adapter, and a long-running `poller/` process. They communicate through a SQLite database. `core/` never imports from the adapters; the adapters are ~5 lines each that call `service.py`.

**Tech Stack:** Python 3.11+, `uv`, `mcp` SDK, SQLAlchemy + Alembic + SQLite (WAL), `httpx`, `pydantic`, `structlog`, `pytest`, `ruff`, `mypy`.

---

## ⚠️ Implementation Update (2026-06-02): Magic Bus uses Clever Devices BusTime, not DoubleMap

Live probing during execution revealed that `mbus.ltp.umich.edu` was rebuilt as
a SPA backed by the **Clever Devices BusTime API v3** at
`https://mbus.ltp.umich.edu/bustime/api/v3`. The DoubleMap `/public/*.json`
endpoints the original plan assumed no longer exist. Confirmed behavior:

- All requests need `?key=<APIKEY>&format=json`. Responses are wrapped in
  `{"bustime-response": {...}}`. Without a key the API returns
  `{"bustime-response":{"error":[{"msg":"No API access key supplied"}]}}`.
- A free developer key requires registering an account via the Magic Bus
  developer portal — document this in the README (Task 16).

**Impact on tasks:**
- **Task 5** (this task) is re-specified below for BusTime. The agency-agnostic
  typed records in `base.py` are unchanged; only the parsing changes.
- **Task 6** (seed) now builds routes, stops, AND `route_stops` from BusTime
  `getpatterns` (the original plan never populated `route_stops` — a latent gap
  this fixes).
- **Task 11** (runner) passes the known route-id list to `get_vehicle_positions`.
- **Task 12** (service) is unaffected — it still calls `get_etas(stop_id)`.

BusTime timestamps are agency-local (`America/Detroit`) with no zone; the client
localizes them, and the `TZDateTime` column type converts to UTC on write.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `.python-version`
- Create: `src/umich_transit/__init__.py`
- Create: `src/umich_transit/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.github/workflows/ci.yml`
- Create: `LICENSE`

- [ ] **Step 1: Create `.python-version` and `.gitignore`**

`.python-version`:
```
3.11
```

`.gitignore`:
```
# Python
__pycache__/
*.py[cod]
*$py.class
.Python
*.egg-info/
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/

# Project
.env
data/
*.db
*.db-journal
*.db-wal
*.db-shm
logs/
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "umich-transit-mcp"
version = "0.1.0"
description = "MCP server that surfaces empirically adjusted U-Mich bus arrival times to Claude"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "Yoav Manor" }]
dependencies = [
    "mcp>=1.0.0",
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "httpx>=0.27",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "structlog>=24.1",
    "anyio>=4.3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "ruff>=0.4",
    "mypy>=1.10",
    "respx>=0.21",
]

[project.scripts]
umich-transit-mcp    = "umich_transit.mcp_server.__main__:main"
umich-transit-poller = "umich_transit.poller.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/umich_transit"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N"]

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 3: Create `.env.example`**

```
# Magic Bus / DoubleMap API base. Verify exact host during Task 5.
MBUS_BASE_URL=https://mbus.ltp.umich.edu

# Optional: API key, if Magic Bus requires one. Leave blank otherwise.
MBUS_API_KEY=

# SQLite path (relative to working dir or absolute)
DATABASE_URL=sqlite:///./data/transit.db

# Poller cadences (seconds)
PREDICTION_POLL_SECONDS=30
ARRIVAL_POLL_SECONDS=15

# Arrival detector thresholds (meters)
ARRIVAL_ENTER_METERS=30
ARRIVAL_EXIT_METERS=50

# Reliability matching window (seconds before arrival to find the prediction)
RELIABILITY_LOOKBACK_SECONDS=300

# Log level
LOG_LEVEL=INFO
```

- [ ] **Step 4: Create the package skeleton**

`src/umich_transit/__init__.py`:
```python
"""U-Mich Transit MCP Server."""
__version__ = "0.1.0"
```

`src/umich_transit/config.py`:
```python
"""Application configuration loaded from environment variables."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mbus_base_url: str = "https://mbus.ltp.umich.edu"
    mbus_api_key: str = ""

    database_url: str = "sqlite:///./data/transit.db"

    prediction_poll_seconds: int = 30
    arrival_poll_seconds: int = 15

    arrival_enter_meters: float = 30.0
    arrival_exit_meters: float = 50.0

    reliability_lookback_seconds: int = 300

    log_level: str = "INFO"

    @property
    def sqlite_path(self) -> Path | None:
        """Return the SQLite file path if the URL is SQLite, else None."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            return Path(self.database_url[len(prefix):])
        return None


settings = Settings()
```

`tests/__init__.py`: (empty)

`tests/conftest.py`:
```python
"""Shared pytest fixtures."""
import os

# Ensure tests never accidentally read a developer's real .env
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("MBUS_BASE_URL", "https://mbus.example.test")
```

- [ ] **Step 5: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      - name: Set up Python
        run: uv python install 3.11
      - name: Install dependencies
        run: uv sync --all-extras
      - name: Lint
        run: uv run ruff check .
      - name: Typecheck
        run: uv run mypy src
      - name: Test
        run: uv run pytest --cov=umich_transit --cov-report=term-missing
```

- [ ] **Step 6: Create `LICENSE` (MIT)**

```
MIT License

Copyright (c) 2026 Yoav Manor

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 7: Install and verify**

Run:
```bash
uv sync --all-extras
uv run python -c "from umich_transit.config import settings; print(settings.mbus_base_url)"
```
Expected: prints `https://mbus.example.test` (the test-environment value from `conftest.py` is NOT loaded here; the real `.env` is absent, so it prints the default `https://mbus.ltp.umich.edu`). Confirms the package imports.

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "feat: project scaffold with config, CI, license"
```

---

## Task 2: Storage — database engine and session factory

**Files:**
- Create: `src/umich_transit/core/__init__.py`
- Create: `src/umich_transit/core/storage/__init__.py`
- Create: `src/umich_transit/core/storage/db.py`
- Create: `tests/core/__init__.py`
- Create: `tests/core/storage/__init__.py`
- Create: `tests/core/storage/test_db.py`

- [ ] **Step 1: Write the failing test**

`tests/core/storage/test_db.py`:
```python
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
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/core/storage/test_db.py -v`
Expected: ImportError or ModuleNotFoundError on `umich_transit.core.storage.db`.

- [ ] **Step 3: Implement `db.py`**

`src/umich_transit/core/__init__.py`: (empty)
`src/umich_transit/core/storage/__init__.py`: (empty)

`src/umich_transit/core/storage/db.py`:
```python
"""Database engine and session management."""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def create_engine_for_url(url: str) -> Engine:
    """Build an Engine; enable WAL + foreign keys for file-backed SQLite."""
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, connect_args=connect_args, future=True)

    if url.startswith("sqlite") and ":memory:" not in url:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Provide a transactional scope; commit on success, rollback on error."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/core/storage/test_db.py -v`
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/core tests/core
git commit -m "feat(storage): engine + session_scope with WAL for SQLite"
```

---

## Task 3: Storage — ORM models

**Files:**
- Create: `src/umich_transit/core/storage/models.py`
- Create: `tests/core/storage/test_models.py`

- [ ] **Step 1: Write the failing test**

`tests/core/storage/test_models.py`:
```python
"""Tests for ORM models: schema, indexes, basic insert/query."""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    Prediction,
    ReliabilityStat,
    Route,
    RouteStop,
    Stop,
)


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return eng


def test_can_insert_and_query_a_route(engine):
    with session_scope(engine) as s:
        s.add(Route(id="1", agency="mbus", short_name="BB", long_name="Bursley-Baits"))
    with session_scope(engine) as s:
        r = s.execute(select(Route).where(Route.id == "1")).scalar_one()
        assert r.short_name == "BB"
        assert r.agency == "mbus"


def test_route_stop_association(engine):
    with session_scope(engine) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="Mason Hall", lat=42.27, lon=-83.74))
        s.add(RouteStop(route_id="r1", stop_id="s1", sequence=1))
    with session_scope(engine) as s:
        rs = s.execute(select(RouteStop)).scalar_one()
        assert rs.route_id == "r1" and rs.stop_id == "s1" and rs.sequence == 1


def test_prediction_and_arrival_have_required_fields(engine):
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="N", lat=0, lon=0))
        s.add(Prediction(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            predicted_arrival_at=now, captured_at=now,
        ))
        s.add(Arrival(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            actual_arrival_at=now, detected_via="proximity",
        ))
    with session_scope(engine) as s:
        assert s.execute(select(Prediction)).scalar_one().vehicle_id == "v1"
        assert s.execute(select(Arrival)).scalar_one().detected_via == "proximity"


def test_reliability_stat_unique_per_bin(engine):
    with session_scope(engine) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="N", lat=0, lon=0))
        s.add(ReliabilityStat(
            route_id="r1", stop_id="s1", dow=1, hour=8,
            on_time_pct=0.75, mean_delay_s=120,
            p50_delay_s=90, p90_delay_s=300, sample_count=42,
            updated_at=datetime.now(UTC),
        ))
    with session_scope(engine) as s:
        stat = s.execute(select(ReliabilityStat)).scalar_one()
        assert stat.on_time_pct == 0.75
        assert stat.sample_count == 42
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/core/storage/test_models.py -v`
Expected: ImportError on `umich_transit.core.storage.models`.

- [ ] **Step 3: Implement `models.py`**

`src/umich_transit/core/storage/models.py`:
```python
"""SQLAlchemy ORM models. Six tables: routes, stops, route_stops,
predictions (high-volume), arrivals, reliability_stats (derived)."""
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Route(Base):
    __tablename__ = "routes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agency: Mapped[str] = mapped_column(String, nullable=False)  # "mbus" | "theride"
    short_name: Mapped[str] = mapped_column(String, nullable=False)
    long_name: Mapped[str] = mapped_column(String, nullable=False)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Stop(Base):
    __tablename__ = "stops"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    agency: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RouteStop(Base):
    __tablename__ = "route_stops"
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"))
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (
        PrimaryKeyConstraint("route_id", "stop_id", "sequence"),
    )


class Prediction(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), nullable=False)
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"), nullable=False)
    vehicle_id: Mapped[str] = mapped_column(String, nullable=False)
    predicted_arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        Index("ix_predictions_stop_route_captured", "stop_id", "route_id", "captured_at"),
        Index("ix_predictions_vehicle_captured", "vehicle_id", "captured_at"),
    )


class Arrival(Base):
    __tablename__ = "arrivals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"), nullable=False)
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"), nullable=False)
    vehicle_id: Mapped[str] = mapped_column(String, nullable=False)
    actual_arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_via: Mapped[str] = mapped_column(String, nullable=False)  # "proximity" | "collapse"
    __table_args__ = (
        Index("ix_arrivals_vehicle_at", "vehicle_id", "actual_arrival_at"),
        Index("ix_arrivals_route_stop_at", "route_id", "stop_id", "actual_arrival_at"),
    )


class ReliabilityStat(Base):
    __tablename__ = "reliability_stats"
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id"))
    stop_id: Mapped[str] = mapped_column(ForeignKey("stops.id"))
    dow: Mapped[int] = mapped_column(Integer, nullable=False)   # 0=Mon..6=Sun
    hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0..23
    on_time_pct: Mapped[float] = mapped_column(Float, nullable=False)
    mean_delay_s: Mapped[float] = mapped_column(Float, nullable=False)
    p50_delay_s: Mapped[float] = mapped_column(Float, nullable=False)
    p90_delay_s: Mapped[float] = mapped_column(Float, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        PrimaryKeyConstraint("route_id", "stop_id", "dow", "hour"),
        Index("ix_reliability_lookup", "route_id", "stop_id", "dow", "hour"),
    )


class ParseError(Base):
    """Rows that failed to parse from upstream payloads. Audit trail."""
    __tablename__ = "parse_errors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # "mbus.etas" etc
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    error: Mapped[str] = mapped_column(String, nullable=False)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/core/storage/test_models.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Initialize Alembic and create the initial migration**

Run:
```bash
uv run alembic init -t generic src/umich_transit/core/storage/migrations
```

Then edit `alembic.ini` `script_location`:
```
script_location = src/umich_transit/core/storage/migrations
```

Edit `src/umich_transit/core/storage/migrations/env.py` — replace its body with:
```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from umich_transit.config import settings
from umich_transit.core.storage.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
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
```

- [ ] **Step 6: Autogenerate and inspect the first migration**

Run:
```bash
mkdir -p data
uv run alembic revision --autogenerate -m "initial schema"
```

Open the generated file in `src/umich_transit/core/storage/migrations/versions/`. Verify it creates all seven tables (`routes`, `stops`, `route_stops`, `predictions`, `arrivals`, `reliability_stats`, `parse_errors`) with the indexes. If any are missing, regenerate after fixing models.

- [ ] **Step 7: Apply the migration and verify**

Run:
```bash
uv run alembic upgrade head
uv run python -c "import sqlite3; print(sorted(r[0] for r in sqlite3.connect('data/transit.db').execute(\"SELECT name FROM sqlite_master WHERE type='table'\")))"
```
Expected output includes: `alembic_version`, `arrivals`, `parse_errors`, `predictions`, `reliability_stats`, `route_stops`, `routes`, `stops`.

- [ ] **Step 8: Commit**

```bash
git add src/umich_transit/core/storage tests/core/storage alembic.ini
git commit -m "feat(storage): ORM models + initial alembic migration"
```

---

## Task 4: Storage — read queries

**Files:**
- Create: `src/umich_transit/core/storage/queries.py`
- Create: `tests/core/storage/test_queries.py`

- [ ] **Step 1: Write the failing test**

`tests/core/storage/test_queries.py`:
```python
"""Tests for read-only query helpers used by the MCP service layer."""
from datetime import UTC, datetime, timedelta

import pytest

from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    Prediction,
    ReliabilityStat,
    Route,
    Stop,
)
from umich_transit.core.storage import queries


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="BB", long_name="Bursley-Baits"))
        s.add(Route(id="r2", agency="theride", short_name="4", long_name="Washtenaw"))
        s.add(Stop(id="s1", agency="mbus", name="Mason Hall", lat=42.27, lon=-83.74))
        s.add(Stop(id="s2", agency="mbus", name="Pierpont Commons", lat=42.29, lon=-83.72))
    return eng


def test_list_routes_filters_by_agency(engine):
    with session_scope(engine) as s:
        all_routes = queries.list_routes(s)
        mbus = queries.list_routes(s, agency="mbus")
        assert len(all_routes) == 2
        assert [r.id for r in mbus] == ["r1"]


def test_find_stops_does_substring_match(engine):
    with session_scope(engine) as s:
        hits = queries.find_stops(s, query="mason")
        assert [h.id for h in hits] == ["s1"]


def test_find_stops_can_sort_by_distance(engine):
    # Point closer to s2 than s1
    near = (42.291, -83.721)
    with session_scope(engine) as s:
        hits = queries.find_stops(s, query="", near=near, limit=2)
        assert [h.id for h in hits] == ["s2", "s1"]


def test_get_reliability_stat_returns_none_when_missing(engine):
    with session_scope(engine) as s:
        result = queries.get_reliability_stat(s, route_id="r1", stop_id="s1", dow=0, hour=8)
        assert result is None


def test_get_reliability_stat_returns_row(engine):
    with session_scope(engine) as s:
        s.add(ReliabilityStat(
            route_id="r1", stop_id="s1", dow=0, hour=8,
            on_time_pct=0.8, mean_delay_s=120,
            p50_delay_s=60, p90_delay_s=300, sample_count=50,
            updated_at=datetime.now(UTC),
        ))
    with session_scope(engine) as s:
        result = queries.get_reliability_stat(s, route_id="r1", stop_id="s1", dow=0, hour=8)
        assert result is not None
        assert result.sample_count == 50


def test_arrivals_in_window(engine):
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        s.add(Arrival(route_id="r1", stop_id="s1", vehicle_id="v1",
                      actual_arrival_at=now - timedelta(days=1),
                      detected_via="proximity"))
        s.add(Arrival(route_id="r1", stop_id="s1", vehicle_id="v1",
                      actual_arrival_at=now - timedelta(days=100),
                      detected_via="proximity"))
    with session_scope(engine) as s:
        recent = queries.arrivals_in_window(
            s, route_id="r1", stop_id="s1",
            since=now - timedelta(days=90), until=now,
        )
        assert len(recent) == 1


def test_prediction_before_arrival(engine):
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        s.add(Prediction(route_id="r1", stop_id="s1", vehicle_id="v1",
                         predicted_arrival_at=now + timedelta(minutes=1),
                         captured_at=now - timedelta(seconds=305)))
        s.add(Prediction(route_id="r1", stop_id="s1", vehicle_id="v1",
                         predicted_arrival_at=now + timedelta(minutes=1),
                         captured_at=now - timedelta(seconds=10)))
    with session_scope(engine) as s:
        match = queries.prediction_for_arrival(
            s, vehicle_id="v1", stop_id="s1",
            arrival_at=now, lookback_seconds=300,
        )
        # Should pick the prediction captured ~5 min before arrival
        assert match is not None
        # The 305-sec-old one is outside the lookback; the 10-sec-old one is inside.
        assert (now - match.captured_at).total_seconds() == pytest.approx(10, abs=1)
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/core/storage/test_queries.py -v`
Expected: ImportError on `umich_transit.core.storage.queries`.

- [ ] **Step 3: Implement `queries.py`**

`src/umich_transit/core/storage/queries.py`:
```python
"""Read-only queries used by the service layer.

All functions take a Session; none manage transactions themselves.
"""
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt

from sqlalchemy import select
from sqlalchemy.orm import Session

from umich_transit.core.storage.models import (
    Arrival,
    Prediction,
    ReliabilityStat,
    Route,
    Stop,
)


def list_routes(session: Session, agency: str | None = None) -> list[Route]:
    stmt = select(Route)
    if agency is not None:
        stmt = stmt.where(Route.agency == agency)
    stmt = stmt.order_by(Route.agency, Route.short_name)
    return list(session.execute(stmt).scalars().all())


def _haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Great-circle distance between two (lat, lon) points, in meters."""
    r_earth_m = 6_371_000.0
    p1, p2 = radians(a_lat), radians(b_lat)
    dphi = radians(b_lat - a_lat)
    dlam = radians(b_lon - a_lon)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlam / 2) ** 2
    return 2 * r_earth_m * asin(sqrt(a))


def find_stops(
    session: Session,
    query: str = "",
    near: tuple[float, float] | None = None,
    limit: int = 5,
) -> list[Stop]:
    stmt = select(Stop)
    if query:
        stmt = stmt.where(Stop.name.ilike(f"%{query}%"))
    rows = list(session.execute(stmt).scalars().all())
    if near is not None:
        lat, lon = near
        rows.sort(key=lambda s: _haversine_m(lat, lon, s.lat, s.lon))
    else:
        rows.sort(key=lambda s: s.name)
    return rows[:limit]


def get_reliability_stat(
    session: Session, *, route_id: str, stop_id: str, dow: int, hour: int,
) -> ReliabilityStat | None:
    stmt = select(ReliabilityStat).where(
        ReliabilityStat.route_id == route_id,
        ReliabilityStat.stop_id == stop_id,
        ReliabilityStat.dow == dow,
        ReliabilityStat.hour == hour,
    )
    return session.execute(stmt).scalar_one_or_none()


def arrivals_in_window(
    session: Session, *, route_id: str, stop_id: str,
    since: datetime, until: datetime,
) -> list[Arrival]:
    stmt = select(Arrival).where(
        Arrival.route_id == route_id,
        Arrival.stop_id == stop_id,
        Arrival.actual_arrival_at >= since,
        Arrival.actual_arrival_at <= until,
    ).order_by(Arrival.actual_arrival_at)
    return list(session.execute(stmt).scalars().all())


def prediction_for_arrival(
    session: Session, *, vehicle_id: str, stop_id: str,
    arrival_at: datetime, lookback_seconds: int,
) -> Prediction | None:
    """Find the prediction captured ~lookback_seconds before the arrival.

    Returns the most recent prediction within the window
    [arrival_at - lookback_seconds, arrival_at].
    """
    window_start = arrival_at - timedelta(seconds=lookback_seconds)
    stmt = (
        select(Prediction)
        .where(
            Prediction.vehicle_id == vehicle_id,
            Prediction.stop_id == stop_id,
            Prediction.captured_at >= window_start,
            Prediction.captured_at <= arrival_at,
        )
        .order_by(Prediction.captured_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/core/storage/test_queries.py -v`
Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/core/storage/queries.py tests/core/storage/test_queries.py
git commit -m "feat(storage): read queries for routes, stops, reliability, arrivals"
```

---

## Task 5: Magic Bus client

**Files:**
- Create: `src/umich_transit/core/clients/__init__.py`
- Create: `src/umich_transit/core/clients/base.py`
- Create: `src/umich_transit/core/clients/mbus.py`
- Create: `tests/core/clients/__init__.py`
- Create: `tests/core/clients/test_mbus.py`
- Create: `tests/fixtures/mbus/routes.json`
- Create: `tests/fixtures/mbus/stops.json`
- Create: `tests/fixtures/mbus/buses.json`
- Create: `tests/fixtures/mbus/etas.json`

- [ ] **Step 1: Discover the real endpoints**

Magic Bus is built on DoubleMap. The public endpoints are typically:
- `GET /public/routes.json`
- `GET /public/stops.json`
- `GET /public/buses.json`
- `GET /public/eta.json?stop=<stop_id>`

Run (interactive — record what you see):
```bash
curl -s "$MBUS_BASE_URL/public/routes.json" | head -c 500
curl -s "$MBUS_BASE_URL/public/stops.json"  | head -c 500
curl -s "$MBUS_BASE_URL/public/buses.json"  | head -c 500
curl -s "$MBUS_BASE_URL/public/eta.json?stop=0001" | head -c 500
```

If any of those 404 or require an API key, check Magic Bus developer signup at `https://mbus.ltp.umich.edu` for the actual paths and auth header. **Write down the exact paths and any auth requirements before proceeding** — they go into `mbus.py` next.

Save one full response from each endpoint into `tests/fixtures/mbus/<endpoint>.json`. Trim to ~3 representative items each so the fixtures stay readable.

- [ ] **Step 2: Write the failing test**

`tests/core/clients/test_mbus.py`:
```python
"""Tests for the Magic Bus client. Uses respx to mock HTTP."""
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx

from umich_transit.core.clients.mbus import MbusClient

FIXTURES = Path(__file__).parents[2] / "fixtures" / "mbus"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
def client():
    return MbusClient(base_url="https://mbus.example.test", http=httpx.AsyncClient())


@pytest.mark.asyncio
@respx.mock
async def test_get_routes_parses_fixture(client):
    respx.get("https://mbus.example.test/public/routes.json").mock(
        return_value=httpx.Response(200, text=_load("routes.json"))
    )
    routes = await client.get_routes()
    assert len(routes) >= 1
    first = routes[0]
    assert first.id
    assert first.short_name
    assert first.long_name


@pytest.mark.asyncio
@respx.mock
async def test_get_stops_parses_fixture(client):
    respx.get("https://mbus.example.test/public/stops.json").mock(
        return_value=httpx.Response(200, text=_load("stops.json"))
    )
    stops = await client.get_stops()
    assert len(stops) >= 1
    s = stops[0]
    assert -90 <= s.lat <= 90
    assert -180 <= s.lon <= 180


@pytest.mark.asyncio
@respx.mock
async def test_get_vehicle_positions_parses_fixture(client):
    respx.get("https://mbus.example.test/public/buses.json").mock(
        return_value=httpx.Response(200, text=_load("buses.json"))
    )
    vehicles = await client.get_vehicle_positions()
    assert len(vehicles) >= 1
    v = vehicles[0]
    assert v.id
    assert v.route_id
    assert v.lat
    assert v.lon


@pytest.mark.asyncio
@respx.mock
async def test_get_etas_parses_fixture(client):
    respx.get("https://mbus.example.test/public/eta.json").mock(
        return_value=httpx.Response(200, text=_load("etas.json"))
    )
    etas = await client.get_etas(stop_id="0001")
    assert len(etas) >= 1
    e = etas[0]
    assert e.route_id
    assert e.stop_id
    assert e.vehicle_id
    assert isinstance(e.predicted_arrival_at, datetime)


@pytest.mark.asyncio
@respx.mock
async def test_get_etas_raises_on_5xx(client):
    respx.get("https://mbus.example.test/public/eta.json").mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_etas(stop_id="0001")
```

- [ ] **Step 3: Run the test — expect failure**

Run: `uv run pytest tests/core/clients/test_mbus.py -v`
Expected: ImportError on `umich_transit.core.clients.mbus`.

- [ ] **Step 4: Implement `clients/base.py` and `clients/mbus.py`**

`src/umich_transit/core/clients/__init__.py`: (empty)

`src/umich_transit/core/clients/base.py`:
```python
"""Typed transit-data records, agency-agnostic.

Clients (`mbus.py`, `theride.py`, ...) all return these types so downstream
code never sees an upstream-specific payload.
"""
from datetime import datetime

from pydantic import BaseModel


class RouteRecord(BaseModel):
    id: str
    agency: str
    short_name: str
    long_name: str
    color: str | None = None
    raw: dict


class StopRecord(BaseModel):
    id: str
    agency: str
    name: str
    lat: float
    lon: float
    raw: dict


class VehicleRecord(BaseModel):
    id: str            # vehicle id
    route_id: str
    lat: float
    lon: float
    heading: float | None = None
    captured_at: datetime


class EtaRecord(BaseModel):
    route_id: str
    stop_id: str
    vehicle_id: str
    predicted_arrival_at: datetime
    captured_at: datetime
```

`src/umich_transit/core/clients/mbus.py`:
```python
"""Magic Bus / DoubleMap client. Returns agency-agnostic typed records.

Endpoint paths verified during Task 5 step 1; adjust the constants if the
real Magic Bus paths differ from the DoubleMap defaults.
"""
from datetime import UTC, datetime, timedelta

import httpx

from umich_transit.core.clients.base import (
    EtaRecord,
    RouteRecord,
    StopRecord,
    VehicleRecord,
)

ROUTES_PATH = "/public/routes.json"
STOPS_PATH = "/public/stops.json"
BUSES_PATH = "/public/buses.json"
ETAS_PATH = "/public/eta.json"


class MbusClient:
    def __init__(self, *, base_url: str, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = http

    async def _get(self, path: str, **params: object) -> object:
        resp = await self._http.get(self._base + path, params=params or None)
        resp.raise_for_status()
        return resp.json()

    async def get_routes(self) -> list[RouteRecord]:
        data = await self._get(ROUTES_PATH)
        # DoubleMap returns a list of dicts: {id, short_name, long_name, color, ...}
        out: list[RouteRecord] = []
        for raw in self._as_list(data):
            out.append(RouteRecord(
                id=str(raw.get("id") or raw.get("route_id")),
                agency="mbus",
                short_name=str(raw.get("short_name") or raw.get("name") or ""),
                long_name=str(raw.get("long_name") or raw.get("name") or ""),
                color=raw.get("color"),
                raw=raw,
            ))
        return out

    async def get_stops(self) -> list[StopRecord]:
        data = await self._get(STOPS_PATH)
        out: list[StopRecord] = []
        for raw in self._as_list(data):
            out.append(StopRecord(
                id=str(raw.get("id") or raw.get("stop_id")),
                agency="mbus",
                name=str(raw.get("name") or raw.get("description") or ""),
                lat=float(raw.get("latitude") or raw.get("lat")),
                lon=float(raw.get("longitude") or raw.get("lon") or raw.get("lng")),
                raw=raw,
            ))
        return out

    async def get_vehicle_positions(self) -> list[VehicleRecord]:
        data = await self._get(BUSES_PATH)
        now = datetime.now(UTC)
        out: list[VehicleRecord] = []
        for raw in self._as_list(data):
            out.append(VehicleRecord(
                id=str(raw.get("id") or raw.get("bus_id")),
                route_id=str(raw.get("route_id") or raw.get("route") or ""),
                lat=float(raw.get("latitude") or raw.get("lat")),
                lon=float(raw.get("longitude") or raw.get("lon") or raw.get("lng")),
                heading=raw.get("heading"),
                captured_at=now,
            ))
        return out

    async def get_etas(self, stop_id: str) -> list[EtaRecord]:
        data = await self._get(ETAS_PATH, stop=stop_id)
        now = datetime.now(UTC)
        out: list[EtaRecord] = []
        for raw in self._as_list(data):
            avg = raw.get("avg") or raw.get("seconds") or raw.get("eta")
            if avg is None:
                continue
            seconds = int(avg)
            out.append(EtaRecord(
                route_id=str(raw.get("route_id") or raw.get("route") or ""),
                stop_id=str(stop_id),
                vehicle_id=str(raw.get("bus_id") or raw.get("vehicle_id") or ""),
                predicted_arrival_at=now + timedelta(seconds=seconds),
                captured_at=now,
            ))
        return out

    @staticmethod
    def _as_list(data: object) -> list[dict]:
        """DoubleMap sometimes returns {"<key>": [...]}, sometimes a bare list."""
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
        if isinstance(data, dict):
            for v in data.values():
                if isinstance(v, list):
                    return [d for d in v if isinstance(d, dict)]
        return []
```

- [ ] **Step 5: Run the test — expect pass**

Run: `uv run pytest tests/core/clients/test_mbus.py -v`
Expected: all 5 tests pass. If a parsing test fails because the fixture shape differs from what the client expects, adjust the field-name fallbacks in the client (the upstream often uses one of several spellings).

- [ ] **Step 6: Commit**

```bash
git add src/umich_transit/core/clients tests/core/clients tests/fixtures
git commit -m "feat(clients): Magic Bus client returning typed records"
```

---

## Task 6: Static-data seeding script

**Files:**
- Create: `scripts/seed_static_data.py`

- [ ] **Step 1: Implement the seeding script**

`scripts/seed_static_data.py`:
```python
"""One-time backfill: pull routes + stops from Magic Bus into the local DB.

Idempotent — re-running upserts.

Usage:
    uv run python scripts/seed_static_data.py
"""
import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Route, Stop


async def main() -> None:
    engine = create_engine_for_url(settings.database_url)
    async with httpx.AsyncClient(timeout=10.0) as http:
        client = MbusClient(base_url=settings.mbus_base_url, http=http)
        routes = await client.get_routes()
        stops = await client.get_stops()

    now = datetime.now(UTC)
    with session_scope(engine) as session:
        for r in routes:
            stmt = sqlite_insert(Route).values(
                id=r.id, agency=r.agency, short_name=r.short_name,
                long_name=r.long_name, color=r.color, raw_json=r.raw,
                updated_at=now,
            )
            session.execute(stmt.on_conflict_do_update(
                index_elements=[Route.id],
                set_={
                    "short_name": r.short_name, "long_name": r.long_name,
                    "color": r.color, "raw_json": r.raw, "updated_at": now,
                },
            ))
        for s in stops:
            stmt = sqlite_insert(Stop).values(
                id=s.id, agency=s.agency, name=s.name,
                lat=s.lat, lon=s.lon, raw_json=s.raw, updated_at=now,
            )
            session.execute(stmt.on_conflict_do_update(
                index_elements=[Stop.id],
                set_={
                    "name": s.name, "lat": s.lat, "lon": s.lon,
                    "raw_json": s.raw, "updated_at": now,
                },
            ))
    print(f"Seeded {len(routes)} routes, {len(stops)} stops.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run it against the real API**

Run:
```bash
uv run python scripts/seed_static_data.py
```
Expected: prints `Seeded N routes, M stops.` with positive N and M. If it fails because of an API path mismatch, fix the constants in `mbus.py` first.

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_static_data.py
git commit -m "feat: one-time script to seed routes and stops from Magic Bus"
```

---

## Task 7: Poller — prediction logger

**Files:**
- Create: `src/umich_transit/poller/__init__.py`
- Create: `src/umich_transit/poller/prediction_logger.py`
- Create: `tests/poller/__init__.py`
- Create: `tests/poller/test_prediction_logger.py`

- [ ] **Step 1: Write the failing test**

`tests/poller/test_prediction_logger.py`:
```python
"""Tests for the prediction logger: takes ETA records, writes Prediction rows."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, Prediction, Route, Stop
from umich_transit.poller.prediction_logger import log_predictions


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="N", lat=0, lon=0))
    return eng


def test_log_predictions_inserts_one_row_per_eta(engine):
    now = datetime.now(UTC)
    etas = [
        EtaRecord(route_id="r1", stop_id="s1", vehicle_id="v1",
                  predicted_arrival_at=now + timedelta(minutes=2), captured_at=now),
        EtaRecord(route_id="r1", stop_id="s1", vehicle_id="v2",
                  predicted_arrival_at=now + timedelta(minutes=5), captured_at=now),
    ]
    with session_scope(engine) as s:
        log_predictions(s, etas)
    with session_scope(engine) as s:
        rows = list(s.execute(select(Prediction)).scalars().all())
        assert len(rows) == 2
        assert {r.vehicle_id for r in rows} == {"v1", "v2"}


def test_log_predictions_skips_unknown_routes(engine, caplog):
    now = datetime.now(UTC)
    etas = [
        EtaRecord(route_id="unknown_route", stop_id="s1", vehicle_id="v1",
                  predicted_arrival_at=now, captured_at=now),
    ]
    with session_scope(engine) as s:
        log_predictions(s, etas)
    with session_scope(engine) as s:
        assert s.execute(select(Prediction)).scalars().first() is None


def test_log_predictions_handles_empty_list(engine):
    with session_scope(engine) as s:
        log_predictions(s, [])  # should not raise
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/poller/test_prediction_logger.py -v`
Expected: ImportError on `umich_transit.poller.prediction_logger`.

- [ ] **Step 3: Implement `prediction_logger.py`**

`src/umich_transit/poller/__init__.py`: (empty)
`tests/poller/__init__.py`: (empty)

`src/umich_transit/poller/prediction_logger.py`:
```python
"""Insert Prediction rows from a batch of ETA records.

Skips ETAs whose route or stop is unknown (not yet seeded). This avoids
foreign-key errors during early runs.
"""
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.storage.models import Prediction, Route, Stop

logger = structlog.get_logger(__name__)


def log_predictions(session: Session, etas: list[EtaRecord]) -> int:
    """Insert one Prediction per ETA. Returns count inserted."""
    if not etas:
        return 0
    known_routes = set(session.execute(select(Route.id)).scalars().all())
    known_stops = set(session.execute(select(Stop.id)).scalars().all())

    rows: list[Prediction] = []
    skipped = 0
    for e in etas:
        if e.route_id not in known_routes or e.stop_id not in known_stops:
            skipped += 1
            continue
        rows.append(Prediction(
            route_id=e.route_id,
            stop_id=e.stop_id,
            vehicle_id=e.vehicle_id,
            predicted_arrival_at=e.predicted_arrival_at,
            captured_at=e.captured_at,
        ))
    if rows:
        session.add_all(rows)
    if skipped:
        logger.warning("log_predictions.skipped_unknown", count=skipped)
    return len(rows)
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/poller/test_prediction_logger.py -v`
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/poller/prediction_logger.py tests/poller
git commit -m "feat(poller): prediction logger writes ETA batches to DB"
```

---

## Task 8: Poller — arrival detector (the algorithmic core)

**Files:**
- Create: `src/umich_transit/poller/arrival_detector.py`
- Create: `tests/poller/test_arrival_detector.py`

- [ ] **Step 1: Write the failing test** (this is the most important test in the project)

`tests/poller/test_arrival_detector.py`:
```python
"""Tests for the hysteresis-based arrival detector.

The detector is a pure function over (state, observation) → (state, events).
We exercise it with synthetic GPS trails.
"""
from datetime import UTC, datetime, timedelta

from umich_transit.core.clients.base import StopRecord, VehicleRecord
from umich_transit.poller.arrival_detector import (
    ArrivalDetector,
    DetectedArrival,
)


def _stops() -> list[StopRecord]:
    # Two stops ~200m apart along an east-west axis
    return [
        StopRecord(id="s1", agency="mbus", name="A",
                   lat=42.0000, lon=-83.0000, raw={}),
        StopRecord(id="s2", agency="mbus", name="B",
                   lat=42.0000, lon=-82.99760, raw={}),  # ~200m east
    ]


def _vehicle(at: datetime, lat: float, lon: float) -> VehicleRecord:
    return VehicleRecord(id="v1", route_id="r1", lat=lat, lon=lon, captured_at=at)


def _route_stops_for_route():
    return {"r1": ["s1", "s2"]}


def test_no_arrival_when_far_away():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    events = detector.observe(_vehicle(t, 42.001, -83.001))  # ~145m from s1
    assert events == []


def test_arrival_emitted_on_entering_threshold():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    # Step 1: approaching, not yet within 30m
    detector.observe(_vehicle(t, 42.0000, -83.0005))  # ~41m from s1
    # Step 2: now within 30m
    events = detector.observe(_vehicle(t + timedelta(seconds=15),
                                       42.0000, -83.00020))  # ~16m
    assert len(events) == 1
    assert events[0].stop_id == "s1"
    assert events[0].vehicle_id == "v1"


def test_no_duplicate_arrival_while_still_at_stop():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    detector.observe(_vehicle(t, 42.0000, -83.00020))           # within 30m
    detector.observe(_vehicle(t + timedelta(seconds=10),
                              42.0000, -83.00018))               # still within
    events = detector.observe(_vehicle(t + timedelta(seconds=20),
                                       42.0000, -83.00015))      # still within
    # Only the first observation should have emitted an arrival
    assert events == []


def test_re_arrival_allowed_after_departure():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    detector.observe(_vehicle(t, 42.0000, -83.00020))            # arrive s1
    detector.observe(_vehicle(t + timedelta(seconds=10),
                              42.0000, -83.0010))                 # depart (>50m)
    events = detector.observe(_vehicle(t + timedelta(seconds=30),
                                       42.0000, -83.00020))       # re-arrive s1
    assert len(events) == 1


def test_gps_jitter_does_not_cause_duplicates():
    # Hysteresis: bouncing between 28m and 35m should not produce two arrivals.
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    detector.observe(_vehicle(t, 42.0000, -83.00020))            # ~16m: ARRIVE
    detector.observe(_vehicle(t + timedelta(seconds=5),
                              42.0000, -83.00040))                 # ~33m: still AT
    events = detector.observe(_vehicle(t + timedelta(seconds=10),
                                       42.0000, -83.00020))        # ~16m: still AT
    assert events == []


def test_state_times_out_after_long_silence():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50, stale_after_seconds=600,
    )
    t = datetime.now(UTC)
    detector.observe(_vehicle(t, 42.0000, -83.00020))   # arrive s1
    # Long gap, then a re-arrival at s1 — should fire because state was dropped
    events = detector.observe(_vehicle(t + timedelta(minutes=20),
                                       42.0000, -83.00020))
    assert len(events) == 1


def test_arrival_record_carries_route_and_timestamp():
    detector = ArrivalDetector(
        stops=_stops(), route_stops=_route_stops_for_route(),
        enter_meters=30, exit_meters=50,
    )
    t = datetime.now(UTC)
    events = detector.observe(_vehicle(t, 42.0000, -83.00020))
    a: DetectedArrival = events[0]
    assert a.route_id == "r1"
    assert a.actual_arrival_at == t
    assert a.detected_via == "proximity"
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/poller/test_arrival_detector.py -v`
Expected: ImportError on `umich_transit.poller.arrival_detector`.

- [ ] **Step 3: Implement the detector**

`src/umich_transit/poller/arrival_detector.py`:
```python
"""Hysteresis-based arrival detector.

State machine per (vehicle_id, stop_id):
    APPROACHING -> AT_STOP   when distance < enter_meters
    AT_STOP     -> DEPARTED  when distance > exit_meters

Only the APPROACHING -> AT_STOP transition emits a DetectedArrival.
After `stale_after_seconds` of no updates, per-vehicle state is dropped.
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from math import asin, cos, radians, sin, sqrt

from umich_transit.core.clients.base import StopRecord, VehicleRecord


class _State(str, Enum):
    APPROACHING = "approaching"
    AT_STOP = "at_stop"


@dataclass(frozen=True)
class DetectedArrival:
    vehicle_id: str
    route_id: str
    stop_id: str
    actual_arrival_at: datetime
    detected_via: str = "proximity"


@dataclass
class _VehicleState:
    last_seen: datetime
    # (vehicle_id, stop_id) -> AT_STOP if currently within exit threshold
    at_stops: dict[str, _State] = field(default_factory=dict)


def _haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r_earth_m = 6_371_000.0
    p1, p2 = radians(a_lat), radians(b_lat)
    dphi = radians(b_lat - a_lat)
    dlam = radians(b_lon - a_lon)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlam / 2) ** 2
    return 2 * r_earth_m * asin(sqrt(a))


class ArrivalDetector:
    def __init__(
        self,
        *,
        stops: list[StopRecord],
        route_stops: dict[str, list[str]],
        enter_meters: float,
        exit_meters: float,
        stale_after_seconds: int = 600,
    ) -> None:
        if exit_meters <= enter_meters:
            raise ValueError("exit_meters must be greater than enter_meters")
        self._stops_by_id = {s.id: s for s in stops}
        self._route_stops = route_stops
        self._enter = enter_meters
        self._exit = exit_meters
        self._stale = timedelta(seconds=stale_after_seconds)
        self._vehicles: dict[str, _VehicleState] = {}

    def observe(self, vehicle: VehicleRecord) -> list[DetectedArrival]:
        self._prune_stale(vehicle.captured_at)

        relevant_stop_ids = self._route_stops.get(vehicle.route_id, [])
        vstate = self._vehicles.get(vehicle.id)
        if vstate is None:
            vstate = _VehicleState(last_seen=vehicle.captured_at)
            self._vehicles[vehicle.id] = vstate
        vstate.last_seen = vehicle.captured_at

        events: list[DetectedArrival] = []
        for stop_id in relevant_stop_ids:
            stop = self._stops_by_id.get(stop_id)
            if stop is None:
                continue
            dist = _haversine_m(vehicle.lat, vehicle.lon, stop.lat, stop.lon)
            current = vstate.at_stops.get(stop_id, _State.APPROACHING)

            if current is _State.APPROACHING and dist < self._enter:
                vstate.at_stops[stop_id] = _State.AT_STOP
                events.append(DetectedArrival(
                    vehicle_id=vehicle.id,
                    route_id=vehicle.route_id,
                    stop_id=stop_id,
                    actual_arrival_at=vehicle.captured_at,
                ))
            elif current is _State.AT_STOP and dist > self._exit:
                # Departed; drop the entry so the next entrance can fire.
                vstate.at_stops.pop(stop_id, None)
            # Otherwise: stay in the same state (hysteresis).
        return events

    def _prune_stale(self, now: datetime) -> None:
        stale = [vid for vid, vs in self._vehicles.items()
                 if now - vs.last_seen > self._stale]
        for vid in stale:
            self._vehicles.pop(vid, None)
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/poller/test_arrival_detector.py -v`
Expected: all 7 tests pass. If any distances are off, recheck the haversine math vs the assertions; the test uses approximate ~16m / ~33m / ~41m / ~145m points.

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/poller/arrival_detector.py tests/poller/test_arrival_detector.py
git commit -m "feat(poller): hysteresis arrival detector with TDD coverage"
```

---

## Task 9: Reliability stats engine

**Files:**
- Create: `src/umich_transit/core/reliability.py`
- Create: `tests/core/test_reliability.py`

- [ ] **Step 1: Write the failing test**

`tests/core/test_reliability.py`:
```python
"""Tests for the reliability stats engine."""
from datetime import UTC, datetime, timedelta

import pytest

from umich_transit.core.reliability import (
    BinKey,
    compute_bin_stats,
    delays_from_pairs,
)


def test_delays_from_pairs_signed_in_seconds():
    pairs = [
        (datetime(2026, 5, 1, 8, 0, tzinfo=UTC),
         datetime(2026, 5, 1, 8, 2, tzinfo=UTC)),  # 2 min late = +120
        (datetime(2026, 5, 1, 8, 5, tzinfo=UTC),
         datetime(2026, 5, 1, 8, 4, tzinfo=UTC)),  # 1 min early = -60
    ]
    delays = delays_from_pairs(pairs)
    assert delays == [120.0, -60.0]


def test_compute_bin_stats_basic():
    delays = [-60, 0, 60, 120, 180, 240, 300, 360, 420, 480]  # 10 samples
    s = compute_bin_stats(delays, on_time_threshold_s=120)
    assert s.sample_count == 10
    assert s.mean_delay_s == pytest.approx(210.0)
    # On-time = |delay| <= 120 → delays -60, 0, 60, 120 → 4 of 10
    assert s.on_time_pct == pytest.approx(0.4)
    assert s.p50_delay_s == pytest.approx(210.0, abs=30)  # median
    assert s.p90_delay_s == pytest.approx(444.0, abs=20)


def test_compute_bin_stats_handles_single_sample():
    s = compute_bin_stats([120.0], on_time_threshold_s=120)
    assert s.sample_count == 1
    assert s.mean_delay_s == 120.0
    assert s.p50_delay_s == 120.0
    assert s.p90_delay_s == 120.0
    assert s.on_time_pct == 1.0


def test_compute_bin_stats_rejects_empty():
    with pytest.raises(ValueError):
        compute_bin_stats([], on_time_threshold_s=120)


def test_bin_key_from_timestamp():
    # Friday 14:00 UTC → dow=4, hour=14
    ts = datetime(2026, 5, 1, 14, 30, tzinfo=UTC)
    key = BinKey.from_timestamp(route_id="r1", stop_id="s1", at=ts)
    assert key.dow == 4 and key.hour == 14
    assert key.route_id == "r1"
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/core/test_reliability.py -v`
Expected: ImportError on `umich_transit.core.reliability`.

- [ ] **Step 3: Implement `reliability.py`**

`src/umich_transit/core/reliability.py`:
```python
"""Reliability stats engine.

Pure functions over numeric delays; no I/O. The nightly batch job will
call these against query results.
"""
from dataclasses import dataclass
from datetime import datetime
from statistics import mean


@dataclass(frozen=True)
class BinKey:
    route_id: str
    stop_id: str
    dow: int   # 0 = Monday
    hour: int  # 0..23

    @classmethod
    def from_timestamp(cls, *, route_id: str, stop_id: str, at: datetime) -> "BinKey":
        return cls(route_id=route_id, stop_id=stop_id, dow=at.weekday(), hour=at.hour)


@dataclass(frozen=True)
class BinStats:
    sample_count: int
    mean_delay_s: float
    p50_delay_s: float
    p90_delay_s: float
    on_time_pct: float


def delays_from_pairs(pairs: list[tuple[datetime, datetime]]) -> list[float]:
    """For a list of (predicted, actual) pairs, return signed delay in seconds.

    Positive = bus arrived later than predicted.
    """
    return [(actual - predicted).total_seconds() for predicted, actual in pairs]


def _percentile(sorted_values: list[float], p: float) -> float:
    """Linear-interpolated percentile (0 <= p <= 1). Input must be sorted."""
    if not sorted_values:
        raise ValueError("empty input")
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = p * (len(sorted_values) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = idx - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def compute_bin_stats(delays: list[float], *, on_time_threshold_s: float) -> BinStats:
    if not delays:
        raise ValueError("compute_bin_stats requires at least one sample")
    sorted_d = sorted(delays)
    on_time = sum(1 for d in delays if abs(d) <= on_time_threshold_s)
    return BinStats(
        sample_count=len(delays),
        mean_delay_s=float(mean(delays)),
        p50_delay_s=_percentile(sorted_d, 0.5),
        p90_delay_s=_percentile(sorted_d, 0.9),
        on_time_pct=on_time / len(delays),
    )
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/core/test_reliability.py -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/core/reliability.py tests/core/test_reliability.py
git commit -m "feat(core): reliability stats engine (pure functions)"
```

---

## Task 10: Nightly stats recomputation job

**Files:**
- Create: `src/umich_transit/poller/stats_job.py`
- Create: `tests/poller/test_stats_job.py`

- [ ] **Step 1: Write the failing test**

`tests/poller/test_stats_job.py`:
```python
"""Tests for the nightly stats recomputation job."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Arrival,
    Base,
    Prediction,
    ReliabilityStat,
    Route,
    Stop,
)
from umich_transit.poller.stats_job import recompute_all_bins


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="X", long_name="X"))
        s.add(Stop(id="s1", agency="mbus", name="N", lat=0, lon=0))
    return eng


def _seed_pair(session, *, dow_hour: datetime, late_seconds: int) -> None:
    """Insert one prediction + one arrival representing the same trip."""
    arrival = dow_hour
    prediction_captured = arrival - timedelta(seconds=60)
    predicted = arrival - timedelta(seconds=late_seconds)
    session.add(Prediction(
        route_id="r1", stop_id="s1", vehicle_id="v1",
        predicted_arrival_at=predicted, captured_at=prediction_captured,
    ))
    session.add(Arrival(
        route_id="r1", stop_id="s1", vehicle_id="v1",
        actual_arrival_at=arrival, detected_via="proximity",
    ))


def test_recompute_creates_stat_row(engine):
    base = datetime(2026, 4, 6, 8, 30, tzinfo=UTC)  # Monday 08:xx
    with session_scope(engine) as s:
        _seed_pair(s, dow_hour=base, late_seconds=60)
        _seed_pair(s, dow_hour=base + timedelta(minutes=10), late_seconds=180)
    recompute_all_bins(engine, lookback_seconds=300, on_time_threshold_s=120)
    with session_scope(engine) as s:
        stat = s.execute(select(ReliabilityStat)).scalar_one()
        assert stat.sample_count == 2
        # One delay 60s (on-time), one 180s (late) → 50% on-time
        assert stat.on_time_pct == pytest.approx(0.5)
        assert stat.mean_delay_s == pytest.approx(120.0)


def test_recompute_idempotent(engine):
    base = datetime(2026, 4, 6, 8, 30, tzinfo=UTC)
    with session_scope(engine) as s:
        _seed_pair(s, dow_hour=base, late_seconds=60)
    recompute_all_bins(engine, lookback_seconds=300, on_time_threshold_s=120)
    recompute_all_bins(engine, lookback_seconds=300, on_time_threshold_s=120)
    with session_scope(engine) as s:
        stats = list(s.execute(select(ReliabilityStat)).scalars().all())
        assert len(stats) == 1  # upserted, not duplicated


def test_recompute_skips_arrivals_with_no_matching_prediction(engine):
    base = datetime(2026, 4, 6, 8, 30, tzinfo=UTC)
    with session_scope(engine) as s:
        s.add(Arrival(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            actual_arrival_at=base, detected_via="proximity",
        ))
    recompute_all_bins(engine, lookback_seconds=300, on_time_threshold_s=120)
    with session_scope(engine) as s:
        assert s.execute(select(ReliabilityStat)).scalars().first() is None
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/poller/test_stats_job.py -v`
Expected: ImportError on `umich_transit.poller.stats_job`.

- [ ] **Step 3: Implement `stats_job.py`**

`src/umich_transit/poller/stats_job.py`:
```python
"""Nightly job that recomputes ReliabilityStat rows from arrivals + predictions."""
from collections import defaultdict
from datetime import UTC, datetime

import structlog
from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from umich_transit.core.reliability import (
    BinKey,
    compute_bin_stats,
    delays_from_pairs,
)
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.models import Arrival, ReliabilityStat
from umich_transit.core.storage.queries import prediction_for_arrival

logger = structlog.get_logger(__name__)


def recompute_all_bins(
    engine: Engine,
    *,
    lookback_seconds: int,
    on_time_threshold_s: float,
) -> int:
    """Walk all arrivals, match each to its 5-min-prior prediction, bin, upsert.

    Returns the number of bins written.
    """
    bins: dict[BinKey, list[float]] = defaultdict(list)
    matched = unmatched = 0

    with session_scope(engine) as s:
        arrivals = list(s.execute(select(Arrival)).scalars().all())
        for a in arrivals:
            pred = prediction_for_arrival(
                s,
                vehicle_id=a.vehicle_id,
                stop_id=a.stop_id,
                arrival_at=a.actual_arrival_at,
                lookback_seconds=lookback_seconds,
            )
            if pred is None:
                unmatched += 1
                continue
            matched += 1
            delays = delays_from_pairs([(pred.predicted_arrival_at, a.actual_arrival_at)])
            key = BinKey.from_timestamp(
                route_id=a.route_id, stop_id=a.stop_id, at=a.actual_arrival_at,
            )
            bins[key].extend(delays)

    now = datetime.now(UTC)
    written = 0
    with session_scope(engine) as s:
        for key, delays in bins.items():
            stats = compute_bin_stats(delays, on_time_threshold_s=on_time_threshold_s)
            stmt = sqlite_insert(ReliabilityStat).values(
                route_id=key.route_id, stop_id=key.stop_id,
                dow=key.dow, hour=key.hour,
                on_time_pct=stats.on_time_pct,
                mean_delay_s=stats.mean_delay_s,
                p50_delay_s=stats.p50_delay_s,
                p90_delay_s=stats.p90_delay_s,
                sample_count=stats.sample_count,
                updated_at=now,
            )
            s.execute(stmt.on_conflict_do_update(
                index_elements=[
                    ReliabilityStat.route_id, ReliabilityStat.stop_id,
                    ReliabilityStat.dow, ReliabilityStat.hour,
                ],
                set_={
                    "on_time_pct": stats.on_time_pct,
                    "mean_delay_s": stats.mean_delay_s,
                    "p50_delay_s": stats.p50_delay_s,
                    "p90_delay_s": stats.p90_delay_s,
                    "sample_count": stats.sample_count,
                    "updated_at": now,
                },
            ))
            written += 1

    logger.info("stats_job.done", matched=matched, unmatched=unmatched, bins=written)
    return written
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/poller/test_stats_job.py -v`
Expected: all 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/poller/stats_job.py tests/poller/test_stats_job.py
git commit -m "feat(poller): nightly stats job recomputes reliability bins"
```

---

## Task 11: Poller runner — wires the three jobs together

**Files:**
- Create: `src/umich_transit/poller/runner.py`
- Create: `src/umich_transit/poller/__main__.py`

- [ ] **Step 1: Implement `runner.py`** (no unit test — orchestration; smoke-tested in Step 4)

`src/umich_transit/poller/runner.py`:
```python
"""Long-running poller. Three independent async tasks:
- prediction logger (every PREDICTION_POLL_SECONDS)
- arrival detector  (every ARRIVAL_POLL_SECONDS)
- stats job         (every 24h)
"""
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy import Engine, select

from umich_transit.config import settings
from umich_transit.core.clients.base import StopRecord
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Arrival, RouteStop, Stop
from umich_transit.poller.arrival_detector import ArrivalDetector
from umich_transit.poller.prediction_logger import log_predictions
from umich_transit.poller.stats_job import recompute_all_bins

logger = structlog.get_logger(__name__)


def _load_detector_context(engine: Engine) -> tuple[list[StopRecord], dict[str, list[str]]]:
    """Read stops and route→stop mapping from the DB to feed the detector."""
    with session_scope(engine) as s:
        stop_rows = list(s.execute(select(Stop)).scalars().all())
        stops = [
            StopRecord(id=r.id, agency=r.agency, name=r.name,
                       lat=r.lat, lon=r.lon, raw=r.raw_json or {})
            for r in stop_rows
        ]
        rs_rows = list(s.execute(select(RouteStop)).scalars().all())
        route_stops: dict[str, list[str]] = {}
        for rs in rs_rows:
            route_stops.setdefault(rs.route_id, []).append(rs.stop_id)
    return stops, route_stops


async def _prediction_loop(engine: Engine, client: MbusClient) -> None:
    interval = settings.prediction_poll_seconds
    backoff = 1.0
    while True:
        try:
            with session_scope(engine) as s:
                stop_ids = [row.id for row in s.execute(select(Stop.id)).all()]
            etas = []
            for sid in stop_ids:
                etas.extend(await client.get_etas(sid))
            with session_scope(engine) as s:
                inserted = log_predictions(s, etas)
            logger.info("prediction_loop.tick", inserted=inserted)
            backoff = 1.0
        except Exception as exc:
            logger.warning("prediction_loop.error", error=str(exc), backoff=backoff)
            await asyncio.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 60)
            continue
        await asyncio.sleep(interval)


async def _arrival_loop(engine: Engine, client: MbusClient) -> None:
    interval = settings.arrival_poll_seconds
    stops, route_stops = _load_detector_context(engine)
    detector = ArrivalDetector(
        stops=stops,
        route_stops=route_stops,
        enter_meters=settings.arrival_enter_meters,
        exit_meters=settings.arrival_exit_meters,
    )
    backoff = 1.0
    while True:
        try:
            vehicles = await client.get_vehicle_positions()
            events = []
            for v in vehicles:
                events.extend(detector.observe(v))
            if events:
                with session_scope(engine) as s:
                    for ev in events:
                        s.add(Arrival(
                            route_id=ev.route_id,
                            stop_id=ev.stop_id,
                            vehicle_id=ev.vehicle_id,
                            actual_arrival_at=ev.actual_arrival_at,
                            detected_via=ev.detected_via,
                        ))
            logger.info("arrival_loop.tick", vehicles=len(vehicles), arrivals=len(events))
            backoff = 1.0
        except Exception as exc:
            logger.warning("arrival_loop.error", error=str(exc), backoff=backoff)
            await asyncio.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 60)
            continue
        await asyncio.sleep(interval)


async def _stats_loop(engine: Engine) -> None:
    while True:
        try:
            recompute_all_bins(
                engine,
                lookback_seconds=settings.reliability_lookback_seconds,
                on_time_threshold_s=120,
            )
        except Exception as exc:
            logger.error("stats_loop.error", error=str(exc))
        # Run nightly at ~03:00 local; for simplicity, sleep 24h after each run.
        await asyncio.sleep(24 * 3600)


async def run() -> None:
    engine = create_engine_for_url(settings.database_url)
    async with httpx.AsyncClient(timeout=10.0) as http:
        client = MbusClient(base_url=settings.mbus_base_url, http=http)
        async with asyncio.TaskGroup() as tg:
            tg.create_task(_prediction_loop(engine, client))
            tg.create_task(_arrival_loop(engine, client))
            tg.create_task(_stats_loop(engine))
```

- [ ] **Step 2: Implement `__main__.py`**

`src/umich_transit/poller/__main__.py`:
```python
"""Entry point: `python -m umich_transit.poller` or `umich-transit-poller`."""
import asyncio
import logging

import structlog

from umich_transit.config import settings
from umich_transit.poller.runner import run


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Lint + typecheck**

Run:
```bash
uv run ruff check src tests
uv run mypy src
```
Expected: no errors. Fix anything that comes up before proceeding.

- [ ] **Step 4: Smoke test — run the poller against the real API for ~60 seconds**

Run:
```bash
uv run python -m umich_transit.poller &
POLLER_PID=$!
sleep 60
kill $POLLER_PID
uv run python -c "import sqlite3; print('predictions:', sqlite3.connect('data/transit.db').execute('SELECT COUNT(*) FROM predictions').fetchone()[0])"
```
Expected: prints `predictions: N` where N > 0. If 0, double-check the seed step ran and that `Stop` rows exist.

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/poller/runner.py src/umich_transit/poller/__main__.py
git commit -m "feat(poller): runner orchestrates prediction, arrival, stats loops"
```

---

## Task 12: Service layer — orchestrates clients + queries + stats

**Files:**
- Create: `src/umich_transit/core/service.py`
- Create: `tests/core/test_service.py`

- [ ] **Step 1: Write the failing test**

`tests/core/test_service.py`:
```python
"""Tests for the service layer that MCP tools and the HTTP API will share."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import (
    Base,
    ReliabilityStat,
    Route,
    Stop,
)


@pytest.fixture
def engine():
    eng = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with session_scope(eng) as s:
        s.add(Route(id="r1", agency="mbus", short_name="BB", long_name="Bursley-Baits"))
        s.add(Stop(id="s1", agency="mbus", name="Mason Hall", lat=42.27, lon=-83.74))
    return eng


@pytest.mark.asyncio
async def test_get_arrivals_adjusts_with_reliability_stat(engine):
    """When a matching stat exists, the service adds adjusted_arrival_at."""
    now = datetime.now(UTC)
    with session_scope(engine) as s:
        s.add(ReliabilityStat(
            route_id="r1", stop_id="s1", dow=now.weekday(), hour=now.hour,
            on_time_pct=0.8, mean_delay_s=180,
            p50_delay_s=120, p90_delay_s=400, sample_count=60,
            updated_at=now,
        ))
    fake_client = AsyncMock()
    fake_client.get_etas = AsyncMock(return_value=[
        EtaRecord(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            predicted_arrival_at=now + timedelta(seconds=60),
            captured_at=now,
        ),
    ])
    svc = TransitService(engine=engine, mbus=fake_client)
    arrivals = await svc.get_arrivals(stop_id="s1")
    assert len(arrivals) == 1
    a = arrivals[0]
    assert a["confidence"] == "high"
    # adjusted = predicted + 180s late
    assert a["adjusted_arrival_at"] == a["predicted_arrival_at"] + timedelta(seconds=180)


@pytest.mark.asyncio
async def test_get_arrivals_low_confidence_when_no_stat(engine):
    now = datetime.now(UTC)
    fake_client = AsyncMock()
    fake_client.get_etas = AsyncMock(return_value=[
        EtaRecord(
            route_id="r1", stop_id="s1", vehicle_id="v1",
            predicted_arrival_at=now + timedelta(seconds=60),
            captured_at=now,
        ),
    ])
    svc = TransitService(engine=engine, mbus=fake_client)
    arrivals = await svc.get_arrivals(stop_id="s1")
    assert arrivals[0]["confidence"] == "low"
    assert arrivals[0]["adjusted_arrival_at"] == arrivals[0]["predicted_arrival_at"]


def test_list_routes_returns_dicts(engine):
    svc = TransitService(engine=engine, mbus=AsyncMock())
    rows = svc.list_routes()
    assert rows == [{
        "id": "r1", "agency": "mbus",
        "short_name": "BB", "long_name": "Bursley-Baits",
        "color": None,
    }]


def test_find_stops_returns_dicts(engine):
    svc = TransitService(engine=engine, mbus=AsyncMock())
    rows = svc.find_stops(query="mason")
    assert rows == [{
        "id": "s1", "agency": "mbus", "name": "Mason Hall",
        "lat": 42.27, "lon": -83.74,
    }]
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/core/test_service.py -v`
Expected: ImportError on `umich_transit.core.service`.

- [ ] **Step 3: Implement `service.py`**

`src/umich_transit/core/service.py`:
```python
"""Service layer: the single API surface used by MCP tools and the future
HTTP layer. Knows how to combine live client calls with DB-backed stats.
"""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.storage.db import session_scope
from umich_transit.core.storage.queries import (
    find_stops as q_find_stops,
    get_reliability_stat,
    list_routes as q_list_routes,
)

CONFIDENCE_THRESHOLD = 50  # sample_count >= → "high"


class TransitService:
    def __init__(self, *, engine: Engine, mbus: MbusClient) -> None:
        self._engine = engine
        self._mbus = mbus

    def list_routes(self, agency: str | None = None) -> list[dict[str, Any]]:
        with session_scope(self._engine) as s:
            routes = q_list_routes(s, agency=agency)
            return [{
                "id": r.id, "agency": r.agency,
                "short_name": r.short_name, "long_name": r.long_name,
                "color": r.color,
            } for r in routes]

    def find_stops(
        self, query: str = "", near: tuple[float, float] | None = None, limit: int = 5,
    ) -> list[dict[str, Any]]:
        with session_scope(self._engine) as s:
            stops = q_find_stops(s, query=query, near=near, limit=limit)
            return [{
                "id": st.id, "agency": st.agency, "name": st.name,
                "lat": st.lat, "lon": st.lon,
            } for st in stops]

    async def get_arrivals(
        self, *, stop_id: str, route_id: str | None = None, limit: int = 5,
    ) -> list[dict[str, Any]]:
        live = await self._mbus.get_etas(stop_id=stop_id)
        if route_id is not None:
            live = [e for e in live if e.route_id == route_id]
        out: list[dict[str, Any]] = []
        with session_scope(self._engine) as s:
            for e in live[:limit]:
                now = datetime.now(UTC)
                stat = get_reliability_stat(
                    s, route_id=e.route_id, stop_id=e.stop_id,
                    dow=now.weekday(), hour=now.hour,
                )
                if stat is not None:
                    adj = e.predicted_arrival_at + _seconds(stat.mean_delay_s)
                    conf = "high" if stat.sample_count >= CONFIDENCE_THRESHOLD else "low"
                    on_time = stat.on_time_pct
                    samples = stat.sample_count
                else:
                    adj = e.predicted_arrival_at
                    conf = "low"
                    on_time = None
                    samples = 0
                out.append({
                    "route_id": e.route_id,
                    "stop_id": e.stop_id,
                    "vehicle_id": e.vehicle_id,
                    "predicted_arrival_at": e.predicted_arrival_at,
                    "adjusted_arrival_at": adj,
                    "on_time_pct_at_this_hour": on_time,
                    "sample_size": samples,
                    "confidence": conf,
                })
        return out

    def route_reliability(
        self, *, route_id: str, day_of_week: int | None = None, hour: int | None = None,
    ) -> dict[str, Any]:
        """Aggregate reliability over all stops on a route, optionally filtered.

        Returns rolled-up means + total samples; per-stop breakdown via
        `stop_reliability` if added later.
        """
        from sqlalchemy import select
        from umich_transit.core.storage.models import ReliabilityStat

        with session_scope(self._engine) as s:
            stmt = select(ReliabilityStat).where(ReliabilityStat.route_id == route_id)
            if day_of_week is not None:
                stmt = stmt.where(ReliabilityStat.dow == day_of_week)
            if hour is not None:
                stmt = stmt.where(ReliabilityStat.hour == hour)
            rows = list(s.execute(stmt).scalars().all())
        if not rows:
            return {"route_id": route_id, "sample_count": 0,
                    "summary": "no data yet"}
        total = sum(r.sample_count for r in rows)
        weighted_mean = sum(r.mean_delay_s * r.sample_count for r in rows) / total
        weighted_on_time = sum(r.on_time_pct * r.sample_count for r in rows) / total
        return {
            "route_id": route_id,
            "sample_count": total,
            "mean_delay_s": weighted_mean,
            "on_time_pct": weighted_on_time,
            "summary": f"{weighted_on_time*100:.0f}% on-time across "
                       f"{total} arrivals; avg delay {weighted_mean:.0f}s",
        }


def _seconds(s: float):
    from datetime import timedelta
    return timedelta(seconds=s)
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/core/test_service.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/core/service.py tests/core/test_service.py
git commit -m "feat(core): service layer for routes, stops, arrivals, reliability"
```

---

## Task 13: MCP server skeleton + `list_routes` tool

**Files:**
- Create: `src/umich_transit/mcp_server/__init__.py`
- Create: `src/umich_transit/mcp_server/server.py`
- Create: `src/umich_transit/mcp_server/tools.py`
- Create: `src/umich_transit/mcp_server/__main__.py`
- Create: `tests/mcp_server/__init__.py`
- Create: `tests/mcp_server/test_tools.py`

- [ ] **Step 1: Write the failing test**

`tests/mcp_server/test_tools.py`:
```python
"""Tests for MCP tool implementations.

These call tool functions directly (not through the MCP transport) — the
adapter is intentionally thin, so a unit-level test is sufficient.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from umich_transit.mcp_server import tools


@pytest.fixture
def fake_service():
    svc = MagicMock()
    svc.list_routes.return_value = [
        {"id": "r1", "agency": "mbus", "short_name": "BB",
         "long_name": "Bursley-Baits", "color": None},
    ]
    return svc


def test_list_routes_tool_returns_summary_and_data(fake_service):
    result = tools.list_routes_tool(fake_service, agency=None)
    assert "summary" in result
    assert "routes" in result
    assert result["routes"][0]["short_name"] == "BB"
    assert "1 route" in result["summary"] or "1 routes" in result["summary"]


def test_list_routes_tool_passes_agency_filter(fake_service):
    tools.list_routes_tool(fake_service, agency="mbus")
    fake_service.list_routes.assert_called_with(agency="mbus")
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/mcp_server/test_tools.py -v`
Expected: ImportError on `umich_transit.mcp_server`.

- [ ] **Step 3: Implement the skeleton + one tool**

`src/umich_transit/mcp_server/__init__.py`: (empty)
`tests/mcp_server/__init__.py`: (empty)

`src/umich_transit/mcp_server/tools.py`:
```python
"""MCP tool implementations. Each function is dumb — it formats inputs,
calls a service method, formats the result. No SQL, no HTTP, no math.
"""
from typing import Any

from umich_transit.core.service import TransitService


def list_routes_tool(svc: TransitService, agency: str | None = None) -> dict[str, Any]:
    """List bus routes, optionally filtered by agency.

    Args:
        agency: "mbus" for campus buses, "theride" for AAATA city buses.

    Returns a dict with `summary` (human-readable) and `routes` (structured).
    """
    routes = svc.list_routes(agency=agency)
    n = len(routes)
    summary = f"{n} route{'s' if n != 1 else ''} found"
    if agency:
        summary += f" for agency={agency}"
    return {"summary": summary, "routes": routes}
```

`src/umich_transit/mcp_server/server.py`:
```python
"""Build and configure the MCP server."""
from contextlib import AsyncExitStack

import httpx
from mcp.server.fastmcp import FastMCP

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url
from umich_transit.mcp_server import tools


def build_server() -> tuple[FastMCP, AsyncExitStack]:
    """Construct an MCP server and the resources it owns.

    Returns the server and an AsyncExitStack the caller must enter at startup
    and exit at shutdown so the underlying httpx.AsyncClient is closed cleanly.
    """
    mcp = FastMCP("umich-transit")
    stack = AsyncExitStack()

    engine = create_engine_for_url(settings.database_url)
    http = httpx.AsyncClient(timeout=10.0)
    mbus = MbusClient(base_url=settings.mbus_base_url, http=http)
    svc = TransitService(engine=engine, mbus=mbus)

    @mcp.tool()
    def list_routes(agency: str | None = None) -> dict:
        """List bus routes. Pass agency='mbus' for U-Mich campus buses
        or agency='theride' for AAATA city buses."""
        return tools.list_routes_tool(svc, agency=agency)

    # Hook the httpx client into the exit stack so it closes cleanly.
    async def _cleanup() -> None:
        await http.aclose()
    stack.push_async_callback(_cleanup)

    return mcp, stack
```

`src/umich_transit/mcp_server/__main__.py`:
```python
"""Entry point for the MCP server."""
import asyncio

from umich_transit.mcp_server.server import build_server


async def _run() -> None:
    mcp, stack = build_server()
    async with stack:
        await mcp.run_stdio_async()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/mcp_server/test_tools.py -v`
Expected: both tests pass.

- [ ] **Step 5: Smoke test the live server with the MCP Inspector**

Run (in one terminal):
```bash
uv run mcp dev src/umich_transit/mcp_server/__main__.py
```
Open the printed URL in your browser, click the `list_routes` tool, run it — it should return your seeded routes.

- [ ] **Step 6: Commit**

```bash
git add src/umich_transit/mcp_server tests/mcp_server
git commit -m "feat(mcp): server skeleton + list_routes tool"
```

---

## Task 14: Remaining MCP tools — `find_stops`, `get_arrivals`, `route_reliability`

**Files:**
- Modify: `src/umich_transit/mcp_server/tools.py`
- Modify: `src/umich_transit/mcp_server/server.py`
- Modify: `tests/mcp_server/test_tools.py`

- [ ] **Step 1: Extend the test file**

Append to `tests/mcp_server/test_tools.py`:
```python
from datetime import UTC, datetime, timedelta


def test_find_stops_tool(fake_service):
    fake_service.find_stops.return_value = [
        {"id": "s1", "agency": "mbus", "name": "Mason Hall",
         "lat": 42.27, "lon": -83.74},
    ]
    result = tools.find_stops_tool(fake_service, query="mason", near=None, limit=5)
    assert "stops" in result
    assert result["stops"][0]["name"] == "Mason Hall"


def test_get_arrivals_tool_formats_summary(fake_service):
    now = datetime.now(UTC)
    fake_service.get_arrivals = AsyncMock(return_value=[{
        "route_id": "r1", "stop_id": "s1", "vehicle_id": "v1",
        "predicted_arrival_at": now + timedelta(minutes=4),
        "adjusted_arrival_at":  now + timedelta(minutes=10),
        "on_time_pct_at_this_hour": 0.6,
        "sample_size": 80, "confidence": "high",
    }])

    import asyncio
    result = asyncio.run(tools.get_arrivals_tool(
        fake_service, stop_id="s1", route_id=None, limit=5))
    assert result["arrivals"][0]["route_id"] == "r1"
    # Summary should mention both raw and adjusted
    assert "4 min" in result["summary"] or "10 min" in result["summary"]


def test_route_reliability_tool(fake_service):
    fake_service.route_reliability.return_value = {
        "route_id": "r1", "sample_count": 200,
        "mean_delay_s": 180.0, "on_time_pct": 0.7,
        "summary": "70% on-time across 200 arrivals; avg delay 180s",
    }
    result = tools.route_reliability_tool(
        fake_service, route_id="r1", day_of_week=None, hour=None,
    )
    assert result["sample_count"] == 200
```

- [ ] **Step 2: Run the new tests — expect failure**

Run: `uv run pytest tests/mcp_server/test_tools.py -v`
Expected: 3 new tests fail with AttributeError on `find_stops_tool`/`get_arrivals_tool`/`route_reliability_tool`.

- [ ] **Step 3: Append to `tools.py`**

Append to `src/umich_transit/mcp_server/tools.py`:
```python
from datetime import UTC, datetime


def find_stops_tool(
    svc: TransitService,
    query: str = "",
    near: tuple[float, float] | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Find bus stops by name, optionally sorted by distance to (lat, lon)."""
    stops = svc.find_stops(query=query, near=near, limit=limit)
    return {
        "summary": f"{len(stops)} stop{'s' if len(stops) != 1 else ''} matching '{query}'",
        "stops": stops,
    }


async def get_arrivals_tool(
    svc: TransitService,
    stop_id: str,
    route_id: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Get upcoming arrivals at a stop, with reliability-adjusted ETAs.

    Each arrival has both `predicted_arrival_at` (what Magic Bus says) and
    `adjusted_arrival_at` (what history suggests).
    """
    arrivals = await svc.get_arrivals(stop_id=stop_id, route_id=route_id, limit=limit)
    now = datetime.now(UTC)
    if not arrivals:
        return {"summary": "No upcoming arrivals at this stop.", "arrivals": []}
    lines = []
    for a in arrivals:
        raw_mins = int((a["predicted_arrival_at"] - now).total_seconds() // 60)
        adj_mins = int((a["adjusted_arrival_at"] - now).total_seconds() // 60)
        if a["confidence"] == "high" and adj_mins != raw_mins:
            lines.append(
                f"Route {a['route_id']}: Magic Bus says {raw_mins} min, "
                f"history suggests ~{adj_mins} min "
                f"({a['on_time_pct_at_this_hour']:.0%} on-time, n={a['sample_size']})"
            )
        else:
            lines.append(
                f"Route {a['route_id']}: {raw_mins} min "
                f"(confidence: {a['confidence']})"
            )
    return {"summary": " | ".join(lines), "arrivals": arrivals}


def route_reliability_tool(
    svc: TransitService,
    route_id: str,
    day_of_week: int | None = None,
    hour: int | None = None,
) -> dict[str, Any]:
    """Reliability stats for a route, optionally filtered by day-of-week
    (0=Mon..6=Sun) and hour (0..23)."""
    return svc.route_reliability(
        route_id=route_id, day_of_week=day_of_week, hour=hour,
    )
```

- [ ] **Step 4: Register the new tools in `server.py`**

Inside `build_server()` in `src/umich_transit/mcp_server/server.py`, add three more `@mcp.tool()` registrations after `list_routes`:

```python
    @mcp.tool()
    def find_stops(query: str = "", near: tuple[float, float] | None = None, limit: int = 5) -> dict:
        """Find bus stops by name. Optionally sort by distance to a (lat, lon)."""
        return tools.find_stops_tool(svc, query=query, near=near, limit=limit)

    @mcp.tool()
    async def get_arrivals(stop_id: str, route_id: str | None = None, limit: int = 5) -> dict:
        """Upcoming arrivals at a stop with both raw and reliability-adjusted ETAs."""
        return await tools.get_arrivals_tool(svc, stop_id=stop_id, route_id=route_id, limit=limit)

    @mcp.tool()
    def route_reliability(route_id: str, day_of_week: int | None = None, hour: int | None = None) -> dict:
        """Reliability stats for a route: on-time %, mean delay, sample count."""
        return tools.route_reliability_tool(
            svc, route_id=route_id, day_of_week=day_of_week, hour=hour,
        )
```

- [ ] **Step 5: Run the tests — expect pass**

Run: `uv run pytest tests/mcp_server/test_tools.py -v`
Expected: all 5 tests pass.

- [ ] **Step 6: Smoke test the live server**

Run `uv run mcp dev src/umich_transit/mcp_server/__main__.py` and exercise each of the four tools in the Inspector UI. All should return without errors.

- [ ] **Step 7: Commit**

```bash
git add src/umich_transit/mcp_server tests/mcp_server
git commit -m "feat(mcp): find_stops, get_arrivals, route_reliability tools"
```

---

## Task 15: Trip planner (`plan_trip` tool)

**Files:**
- Create: `src/umich_transit/core/planner.py`
- Create: `tests/core/test_planner.py`
- Modify: `src/umich_transit/core/service.py`
- Modify: `src/umich_transit/mcp_server/tools.py`
- Modify: `src/umich_transit/mcp_server/server.py`

- [ ] **Step 1: Write the failing test (planner is pure)**

`tests/core/test_planner.py`:
```python
"""Tests for the same-route trip planner.

V1 supports only trips where one route visits both stops. Transfers come in v2.
"""
from datetime import UTC, datetime, timedelta

import pytest

from umich_transit.core.planner import TripPlanner, TripSegment


def _arrivals_factory(now, mins_until, route_id, vehicle):
    return {
        "route_id": route_id, "stop_id": "s1", "vehicle_id": vehicle,
        "predicted_arrival_at": now + timedelta(minutes=mins_until),
        "adjusted_arrival_at":  now + timedelta(minutes=mins_until + 1),
        "on_time_pct_at_this_hour": 0.7, "sample_size": 60, "confidence": "high",
    }


def test_no_plan_when_no_common_route():
    planner = TripPlanner(
        route_stops={"r1": ["s1", "s2"], "r2": ["s3", "s4"]},
        stop_to_routes={"s1": ["r1"], "s2": ["r1"], "s3": ["r2"], "s4": ["r2"]},
    )
    plan = planner.plan(
        from_stop_id="s1", to_stop_id="s3",
        upcoming_arrivals=[],
    )
    assert plan is None


def test_picks_soonest_common_route():
    now = datetime.now(UTC)
    planner = TripPlanner(
        route_stops={"r1": ["s1", "s2"]},
        stop_to_routes={"s1": ["r1"], "s2": ["r1"]},
    )
    arrivals = [
        _arrivals_factory(now, mins_until=15, route_id="r1", vehicle="v_late"),
        _arrivals_factory(now, mins_until=4,  route_id="r1", vehicle="v_soon"),
    ]
    plan = planner.plan(from_stop_id="s1", to_stop_id="s2", upcoming_arrivals=arrivals)
    assert plan is not None
    assert plan.segments[0].vehicle_id == "v_soon"
    assert isinstance(plan.segments[0], TripSegment)


def test_rejects_arrivals_for_wrong_route():
    now = datetime.now(UTC)
    planner = TripPlanner(
        route_stops={"r1": ["s1", "s2"], "r2": ["s1", "s9"]},
        stop_to_routes={"s1": ["r1", "r2"], "s2": ["r1"], "s9": ["r2"]},
    )
    arrivals = [
        _arrivals_factory(now, mins_until=2, route_id="r2", vehicle="vx"),  # wrong route
        _arrivals_factory(now, mins_until=8, route_id="r1", vehicle="vy"),  # correct
    ]
    plan = planner.plan(from_stop_id="s1", to_stop_id="s2", upcoming_arrivals=arrivals)
    assert plan is not None
    assert plan.segments[0].vehicle_id == "vy"
```

- [ ] **Step 2: Run the test — expect failure**

Run: `uv run pytest tests/core/test_planner.py -v`
Expected: ImportError on `umich_transit.core.planner`.

- [ ] **Step 3: Implement `planner.py`**

`src/umich_transit/core/planner.py`:
```python
"""Same-route trip planner. Given upcoming arrivals at `from_stop_id` and
the route→stops mapping, returns the soonest single-route trip to
`to_stop_id`, or None if there is no shared route."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TripSegment:
    mode: str         # "bus"
    route_id: str
    vehicle_id: str
    from_stop_id: str
    to_stop_id: str
    board_at: datetime
    adjusted_arrival_at: datetime


@dataclass(frozen=True)
class TripPlan:
    segments: list[TripSegment]


class TripPlanner:
    def __init__(
        self,
        *,
        route_stops: dict[str, list[str]],
        stop_to_routes: dict[str, list[str]],
    ) -> None:
        self._route_stops = route_stops
        self._stop_to_routes = stop_to_routes

    def plan(
        self,
        *,
        from_stop_id: str,
        to_stop_id: str,
        upcoming_arrivals: list[dict[str, Any]],
    ) -> TripPlan | None:
        common = set(self._stop_to_routes.get(from_stop_id, [])) & set(
            self._stop_to_routes.get(to_stop_id, [])
        )
        if not common:
            return None

        candidates = [a for a in upcoming_arrivals if a["route_id"] in common]
        if not candidates:
            return None
        candidates.sort(key=lambda a: a["adjusted_arrival_at"])
        chosen = candidates[0]
        seg = TripSegment(
            mode="bus",
            route_id=chosen["route_id"],
            vehicle_id=chosen["vehicle_id"],
            from_stop_id=from_stop_id,
            to_stop_id=to_stop_id,
            board_at=chosen["adjusted_arrival_at"],
            # V1 approximation: arrival at destination = board_at + a per-route stub.
            # Real travel time computation deferred; pulled from schedule in v2.
            adjusted_arrival_at=chosen["adjusted_arrival_at"],
        )
        return TripPlan(segments=[seg])
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/core/test_planner.py -v`
Expected: all 3 tests pass.

- [ ] **Step 5: Add `plan_trip` to the service and tools**

Append to `src/umich_transit/core/service.py` inside the `TransitService` class:
```python
    async def plan_trip(
        self, *, from_stop_id: str, to_stop_id: str,
    ) -> dict[str, Any] | None:
        from sqlalchemy import select
        from umich_transit.core.planner import TripPlanner
        from umich_transit.core.storage.models import RouteStop

        with session_scope(self._engine) as s:
            rs_rows = list(s.execute(select(RouteStop)).scalars().all())
        route_stops: dict[str, list[str]] = {}
        stop_to_routes: dict[str, list[str]] = {}
        for rs in rs_rows:
            route_stops.setdefault(rs.route_id, []).append(rs.stop_id)
            stop_to_routes.setdefault(rs.stop_id, []).append(rs.route_id)

        upcoming = await self.get_arrivals(stop_id=from_stop_id)
        planner = TripPlanner(route_stops=route_stops, stop_to_routes=stop_to_routes)
        plan = planner.plan(
            from_stop_id=from_stop_id, to_stop_id=to_stop_id,
            upcoming_arrivals=upcoming,
        )
        if plan is None:
            return {"summary": "No same-route trip available.", "plan": None}
        seg = plan.segments[0]
        return {
            "summary": f"Take route {seg.route_id} (vehicle {seg.vehicle_id}) "
                       f"from {seg.from_stop_id} to {seg.to_stop_id}",
            "plan": {
                "segments": [{
                    "mode": seg.mode,
                    "route_id": seg.route_id,
                    "vehicle_id": seg.vehicle_id,
                    "from_stop_id": seg.from_stop_id,
                    "to_stop_id": seg.to_stop_id,
                    "board_at": seg.board_at.isoformat(),
                    "adjusted_arrival_at": seg.adjusted_arrival_at.isoformat(),
                }],
            },
        }
```

Append to `src/umich_transit/mcp_server/tools.py`:
```python
async def plan_trip_tool(
    svc: TransitService, from_stop_id: str, to_stop_id: str,
) -> dict[str, Any]:
    """Plan a single-route bus trip from one stop to another (v1: no transfers)."""
    result = await svc.plan_trip(from_stop_id=from_stop_id, to_stop_id=to_stop_id)
    return result or {"summary": "No plan.", "plan": None}
```

In `src/umich_transit/mcp_server/server.py`, inside `build_server()` after the other tools, add:
```python
    @mcp.tool()
    async def plan_trip(from_stop_id: str, to_stop_id: str) -> dict:
        """Plan a single-route bus trip from `from_stop_id` to `to_stop_id`.
        Returns the soonest reliability-adjusted option, or null if no single
        route connects the two stops."""
        return await tools.plan_trip_tool(
            svc, from_stop_id=from_stop_id, to_stop_id=to_stop_id,
        )
```

- [ ] **Step 6: Smoke test**

Run `uv run mcp dev src/umich_transit/mcp_server/__main__.py`, call `plan_trip` with two stop IDs that share a route. Verify a segment is returned.

- [ ] **Step 7: Commit**

```bash
git add src/umich_transit/core/planner.py tests/core/test_planner.py \
        src/umich_transit/core/service.py src/umich_transit/mcp_server
git commit -m "feat: same-route trip planner with plan_trip MCP tool"
```

---

## Task 16: README, demo, repo polish

**Files:**
- Create: `README.md`
- Create: `CHANGELOG.md`
- Create: `screenshots/` (directory + at least one image)
- Modify: `pyproject.toml` (pre-commit hook deps)

- [ ] **Step 1: Write the README**

`README.md`:
```markdown
# U-Mich Transit MCP Server

An MCP server that gives Claude reliable answers about University of Michigan
buses. It does not just wrap the Magic Bus arrival predictions — it logs them,
infers actual arrivals from GPS, and surfaces empirically adjusted ETAs.

> "Magic Bus says 4 min. The bus shows up in 12.
> This server learns from that gap."

![Demo](screenshots/demo.gif)

## What it does

Six MCP tools, all read-only:

| Tool | Use it for |
|---|---|
| `list_routes` | Discover routes; filter by agency |
| `find_stops` | Search stops by name; sort by distance |
| `get_arrivals` | **Headline tool.** Live ETA + history-adjusted ETA + confidence |
| `route_reliability` | On-time %, mean delay, sample count for a route |
| `plan_trip` | Same-route bus trip planner with reliability-aware arrival |
| `stop_reliability` *(stretch)* | Per-stop reliability detail |

## Architecture

```
┌────────────────┐                           ┌─────────────────────┐
│  MCP Server    │   ┌────────────────┐      │  Next.js Frontend   │
│  (thin)        │   │  HTTP API      │      │  (planned)          │
└────────┬───────┘   │  (planned)     │      └──────────┬──────────┘
         │           └────────┬───────┘                 │
         ▼                    ▼                         ▼
┌──────────────────────────────────────┐
│  umich_transit.core                  │
│    clients · storage · reliability   │
│    planner · service                 │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  SQLite (→ Postgres for the app)     │
└──────────▲───────────────────────────┘
           │
┌──────────┴───────────────────────────┐
│  Background Poller                   │
│    prediction logger (30s)           │
│    arrival detector (15s)            │
│    nightly stats job                 │
└──────────────────────────────────────┘
```

The poller and the MCP server are independent processes that communicate
through the database.

## Quickstart

```bash
git clone https://github.com/<you>/umich-transit-mcp.git
cd umich-transit-mcp
uv sync --all-extras
cp .env.example .env
uv run alembic upgrade head
uv run python scripts/seed_static_data.py
uv run python -m umich_transit.poller  # run continuously in one terminal
```

Add to your Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "umich-transit": {
      "command": "uv",
      "args": ["run", "umich-transit-mcp"],
      "cwd": "/absolute/path/to/umich-transit-mcp"
    }
  }
}
```

## How reliability scoring works

For every prediction the API publishes, the poller stores
`(vehicle, stop, predicted_arrival_at, captured_at)`. Separately, the poller
watches vehicle GPS positions and infers arrivals using a hysteresis state
machine — bus enters 30m of a stop → arrival event; bus must leave 50m to
re-arm. Nightly, the system pairs each detected arrival with the prediction
made ~5 minutes earlier, computes a signed delay, and bins by
(route, stop, day-of-week, hour-of-day). The live `get_arrivals` tool reads
that bin and adds the mean historical delay to the published ETA.

Confidence is "high" when a bin has ≥ 50 samples; otherwise "low" and the
adjustment is suppressed.

## FAQ

**Why SQLite, not Postgres?**
Zero ops cost, ships with Python, handles 1M rows/day comfortably in WAL mode.
The data layer is SQLAlchemy, so swapping to Postgres for a multi-user app
is a one-line change.

**Why a separate poller process?**
The poller must run continuously to collect history. The MCP server is
launched on demand by Claude clients. Coupling them would mean either losing
data when the client closes or running the poller every time someone asks
a question.

**Why not just use the GTFS-realtime feed?**
The campus Magic Bus system is built on DoubleMap, which publishes its own
prediction API. TheRide (AAATA) ships GTFS-RT, which is on the roadmap.

## Roadmap

- TheRide GTFS-RT client (Ann Arbor city buses)
- `stop_reliability` tool
- FastAPI HTTP layer wrapping the same `core/`
- Next.js dashboard with route reliability heatmaps
- Service-alert ingestion
- Crowdsourced arrival reports

## Development

```bash
uv run ruff check .
uv run mypy src
uv run pytest --cov=umich_transit
```

## License

MIT
```

- [ ] **Step 2: Create a `CHANGELOG.md`**

`CHANGELOG.md`:
```markdown
# Changelog

## [Unreleased]

### Added
- Initial release.
- Magic Bus client returning typed records.
- SQLite-backed storage layer with Alembic migrations.
- Background poller: prediction logger, hysteresis arrival detector, nightly stats job.
- MCP server with five tools: list_routes, find_stops, get_arrivals,
  route_reliability, plan_trip.
- README with architecture diagram, quickstart, and FAQ.
```

- [ ] **Step 3: Generate the demo GIF**

In Claude Desktop, after the poller has collected ~24h of data:

1. Open a chat with the U-Mich Transit MCP server connected.
2. Ask: "What's the soonest bus from Mason Hall to Pierpont Commons?"
3. Record the screen (Cmd+Shift+5 → "Record selected portion") for ~20 seconds.
4. Convert to GIF (e.g. `ffmpeg -i demo.mov -vf "fps=10,scale=900:-1" screenshots/demo.gif`).
5. Commit the GIF.

- [ ] **Step 4: Final repo check**

Run:
```bash
uv run ruff check .
uv run mypy src
uv run pytest --cov=umich_transit --cov-report=term-missing
```
Expected: green across the board, coverage on `core/` ≥ 80%.

- [ ] **Step 5: Set GitHub topic tags after pushing**

After pushing to GitHub, on the repo home page click the gear next to "About"
and add topics: `mcp`, `model-context-protocol`, `university-of-michigan`,
`transit`, `python`.

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md screenshots/
git commit -m "docs: README with architecture, quickstart, FAQ; demo gif"
```

---

## Self-review notes

**Spec coverage check** (every spec section maps to a task):
- Architecture / two processes → Tasks 1, 11, 13
- App-ready core seam → Task 12 (service), enforced by import direction in Tasks 5/12/13
- Six tools → list_routes (T13), find_stops/get_arrivals/route_reliability (T14), plan_trip (T15). `stop_reliability` is in the spec as stretch and listed in the README roadmap; intentionally deferred to keep the MVP plan finite.
- Six-table data model → Task 3 (all six + `parse_errors`)
- Indexes → Task 3 step 3
- Prediction logger → Task 7
- Arrival detector with hysteresis → Task 8 (the centerpiece, TDD-first)
- Nightly stats job → Task 10
- Error handling (backoff, parse_errors, graceful degradation) → Task 11 (`_prediction_loop`/`_arrival_loop` backoff), Task 12 (cold-start "low" confidence)
- README plan (8 sections) → Task 16
- CI / lint / typecheck → Task 1 step 5 + Task 11 step 3 + Task 16 step 4
- Repo polish (LICENSE, badges-ready CI, topic tags) → Tasks 1, 16

**Placeholder check:** no "TBD"/"TODO" left in any task. The single open item the spec called out (verifying actual Magic Bus endpoints) is Task 5 Step 1, which is a real engineering step, not a placeholder.

**Type consistency check:** `MbusClient.get_etas(stop_id)` is called the same way in Tasks 7, 11, 12, 13, 14. `EtaRecord`, `RouteRecord`, `StopRecord`, `VehicleRecord` are defined once in `base.py` and reused. `DetectedArrival` from Task 8 is materialized into the `Arrival` ORM model in Task 11's `_arrival_loop`. `BinKey`/`BinStats` from Task 9 are consumed in Task 10. `TripPlanner.plan(...)` signature in Task 15 step 3 matches what `service.plan_trip` calls in step 5. All consistent.
