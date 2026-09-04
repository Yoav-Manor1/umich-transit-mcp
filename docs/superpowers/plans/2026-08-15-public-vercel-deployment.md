# Public Vercel Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a deterministic recruiter-facing demo of U-Mich Transit on Vercel, while preparing the shared data layer for a later live PostgreSQL deployment without breaking local SQLite or MCP workflows.

**Architecture:** A `WebTransitService` protocol keeps FastAPI independent of its data source. Demo mode uses an in-memory service backed by versioned JSON fixtures; local/live mode uses the existing SQLAlchemy and BusTime service. Vercel imports one root FastAPI entry point, while the continuous poller remains a separately deployed container. PostgreSQL differences are isolated in engine URL normalization and dialect-specific upsert construction.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, psycopg 3, Pydantic Settings, Pytest, Ruff, strict MyPy, Vercel Python runtime

**Spec:** `docs/superpowers/specs/2026-08-15-public-vercel-deployment-design.md`

## Global Constraints

- Phase 1 must deploy in explicit `TRANSIT_APP_MODE=demo` without a database or BusTime secret.
- Phase-one fixture data remains identifiable through API metadata and operational documentation.
- Live Vercel mode requires `DATABASE_URL` and `MBUS_API_KEY`; missing configuration fails closed.
- SQLite remains supported for local development, tests, and the stdio MCP workflow.
- The continuous poller never runs inside a Vercel request function.
- No domain purchase, DNS mutation, or paid resource is authorized by this plan.
- Every production behavior follows test-first red-green-refactor development.

---

### Task 1: Runtime mode and web-service boundary

**Files:**
- Create: `src/umich_transit/web/protocols.py`
- Create: `src/umich_transit/web/runtime.py`
- Modify: `src/umich_transit/config.py`
- Modify: `src/umich_transit/web/app.py`
- Test: `tests/web/test_runtime.py`
- Test: `tests/web/test_api.py`

**Interfaces:**
- Produces: `AppMode = Literal["local", "demo", "live"]`
- Produces: `resolve_app_mode(configured: str | None, *, on_vercel: bool) -> AppMode`
- Produces: `WebTransitService` protocol with `find_stops`, `get_arrivals`, `prediction_accuracy`, and `readiness`
- Produces: `build_runtime_app() -> FastAPI`
- Consumes: existing `TransitService`, `Settings`, and `build_app`

- [ ] **Step 1: Write failing runtime-mode tests**

```python
import pytest

from umich_transit.web.runtime import resolve_app_mode


def test_explicit_demo_mode():
    assert resolve_app_mode("demo", on_vercel=True) == "demo"


def test_local_mode_is_default_off_vercel():
    assert resolve_app_mode(None, on_vercel=False) == "local"


def test_vercel_requires_explicit_mode():
    with pytest.raises(ValueError, match="TRANSIT_APP_MODE"):
        resolve_app_mode(None, on_vercel=True)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="local, demo, or live"):
        resolve_app_mode("preview", on_vercel=False)
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest tests/web/test_runtime.py -q`

Expected: collection fails because `umich_transit.web.runtime` does not exist.

- [ ] **Step 3: Implement the mode parser and protocol minimally**

`protocols.py` defines a runtime-checkable typing protocol using the existing
JSON-compatible response shapes. `runtime.py` implements only
`resolve_app_mode`; do not construct services yet. Add optional
`transit_app_mode` and Vercel environment detection fields to `Settings`
without changing existing local defaults.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `uv run pytest tests/web/test_runtime.py -q`

Expected: all runtime-mode tests pass.

- [ ] **Step 5: Write a failing app-boundary test**

Add a minimal fake satisfying `WebTransitService` and assert that
`build_app(fake, app_mode="demo")` returns `{"status": "ok", "mode": "demo"}`
from `/api/health`.

- [ ] **Step 6: Run the boundary test and verify RED**

Run: `uv run pytest tests/web/test_api.py::test_health_reports_application_mode -q`

Expected: `build_app` rejects `app_mode` or health omits `mode`.

- [ ] **Step 7: Generalize `build_app` to the protocol and pass mode metadata**

Keep `TransitService` injection backward-compatible. Add `app_mode="local"`
and an optional zero-argument readiness callback. Do not add demo fixtures in
this task.

- [ ] **Step 8: Run web tests and commit**

Run: `uv run pytest tests/web -q`

```bash
git add src/umich_transit/config.py src/umich_transit/web/protocols.py src/umich_transit/web/runtime.py src/umich_transit/web/app.py tests/web/test_runtime.py tests/web/test_api.py
git commit -m "feat(web): add explicit runtime modes"
```

---

### Task 2: Deterministic in-memory demo service

**Files:**
- Create: `src/umich_transit/demo/__init__.py`
- Create: `src/umich_transit/demo/service.py`
- Create: `src/umich_transit/demo/fixtures/showcase.json`
- Modify: `src/umich_transit/web/runtime.py`
- Test: `tests/demo/test_service.py`
- Test: `tests/demo/__init__.py`
- Test: `tests/web/test_runtime.py`

**Interfaces:**
- Produces: `DemoTransitService(fixture_path: Path | None = None, now_factory: Callable[[], datetime] = ...)`
- Produces: `DemoTransitService.readiness() -> dict[str, Any]`
- Produces: `DemoTransitService.prediction_accuracy(route_id: str | None = None) -> dict[str, Any]`
- Produces: `build_runtime_service(mode: AppMode, settings: Settings) -> WebTransitService`

- [ ] **Step 1: Add a versioned fixture**

The JSON contains `version`, `reference_time`, two routes, three named U-M
stops, at least three upcoming-arrival offsets, high- and low-confidence
examples, and explicitly illustrative accuracy metrics. Store offsets rather
than future absolute timestamps so the demo remains usable indefinitely.

- [ ] **Step 2: Write failing demo-service tests**

```python
from datetime import UTC, datetime

import pytest

from umich_transit.demo.service import DemoTransitService

NOW = datetime(2026, 8, 15, 16, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_demo_arrivals_shift_relative_to_now():
    svc = DemoTransitService(now_factory=lambda: NOW)
    arrivals = await svc.get_arrivals(stop_id="CCTC")
    assert arrivals[0]["predicted_arrival_at"] > NOW
    assert arrivals[0]["data_source"] == "demo"


def test_demo_accuracy_is_explicitly_illustrative():
    report = DemoTransitService(now_factory=lambda: NOW).prediction_accuracy()
    assert report["status"] == "illustrative"
    assert report["data_source"] == "demo"
```

Also test case-insensitive stop search, unknown stops, deterministic ordering,
route filtering, and readiness metadata.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `uv run pytest tests/demo/test_service.py -q`

Expected: import fails because the demo service does not exist.

- [ ] **Step 4: Implement the fixture loader and demo service minimally**

Validate fixture version and required top-level keys. Convert arrival offsets
to aware UTC datetimes at request time. Never open a database or instantiate an
HTTP client in demo mode.

- [ ] **Step 5: Run demo tests and verify GREEN**

Run: `uv run pytest tests/demo/test_service.py -q`

- [ ] **Step 6: Write a failing runtime-factory test**

Patch live constructors to raise if called, build demo mode, and assert the
returned object is `DemoTransitService`. Add a live-mode test that rejects an
empty BusTime key or non-PostgreSQL Vercel database URL.

- [ ] **Step 7: Implement runtime service construction and verify**

Run: `uv run pytest tests/web/test_runtime.py tests/demo/test_service.py -q`

- [ ] **Step 8: Commit**

```bash
git add src/umich_transit/demo src/umich_transit/web/runtime.py tests/demo tests/web/test_runtime.py
git commit -m "feat(demo): add deterministic showcase service"
```

---

### Task 3: Public demo API and recruiter-facing interface

**Files:**
- Modify: `src/umich_transit/web/app.py`
- Modify: `src/umich_transit/web/static/index.html`
- Modify: `src/umich_transit/web/static/app.js`
- Modify: `src/umich_transit/web/static/style.css`
- Test: `tests/web/test_api.py`
- Create: `tests/web/test_public_page.py`

**Interfaces:**
- Produces: `GET /api/ready`
- Produces: `GET /api/accuracy?route_id=<optional>`
- Preserves: `GET /api/stops/search` and `GET /api/arrivals`

- [ ] **Step 1: Write failing API tests**

```python
def test_demo_readiness_is_visible(demo_client):
    response = demo_client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["mode"] == "demo"


def test_demo_accuracy_is_labeled(demo_client):
    response = demo_client.get("/api/accuracy")
    assert response.status_code == 200
    assert response.json()["status"] == "illustrative"
```

Add tests that live readiness returns 503 when its callback reports unavailable
and that API responses never contain configured secret values.

- [ ] **Step 2: Run API tests and verify RED**

Run: `uv run pytest tests/web/test_api.py -q`

Expected: readiness and accuracy routes return 404.

- [ ] **Step 3: Implement readiness and accuracy endpoints minimally**

Add `Cache-Control: no-store` to live data and readiness responses. Preserve
the current upstream-error shape for arrivals.

- [ ] **Step 4: Run API tests and verify GREEN**

Run: `uv run pytest tests/web/test_api.py -q`

- [ ] **Step 5: Write failing public-page contract tests**

Assert `/` contains the outcome-led headline, `Live board`, `Accuracy`, `How it
works`, GitHub link, methodology link, and accessible tab button labels, without
rendering demo labels. Assert no horizontal-scrolling layout rule such as fixed
pixel page width is introduced.

- [ ] **Step 6: Run page tests and verify RED**

Run: `uv run pytest tests/web/test_public_page.py -q`

Expected: the current minimal page lacks the required showcase content.

- [ ] **Step 7: Implement the public page**

Create a mobile-first two-view interface. The first viewport explains the
problem and clearly identifies demo mode. The live board compares published
and adjusted estimates with confidence and sample count. The accuracy view
renders mean absolute error, within-two-minutes rate, and sample count. Keep the
existing favorites and walk-time behavior.

- [ ] **Step 8: Run page and web tests, then commit**

Run: `uv run pytest tests/web -q`

```bash
git add src/umich_transit/web tests/web
git commit -m "feat(web): build recruiter-facing transit showcase"
```

---

### Task 4: Vercel entry point and deployable build

**Files:**
- Create: `app.py`
- Create: `vercel.json`
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Test: `tests/web/test_vercel_entrypoint.py`

**Interfaces:**
- Produces: root module `app: FastAPI`
- Produces: Vercel configuration setting `TRANSIT_APP_MODE=demo` for Phase 1

- [ ] **Step 1: Write the failing entry-point test**

```python
def test_vercel_entrypoint_exports_demo_fastapi(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TRANSIT_APP_MODE", "demo")
    module = importlib.import_module("app")
    assert isinstance(module.app, FastAPI)
    with TestClient(module.app) as client:
        assert client.get("/api/health").json()["mode"] == "demo"
```

- [ ] **Step 2: Run the test and verify RED**

Run: `uv run pytest tests/web/test_vercel_entrypoint.py -q`

Expected: root `app` module does not exist.

- [ ] **Step 3: Implement the entry point and Vercel configuration**

`app.py` contains only `app = build_runtime_app()`. `vercel.json` sets the demo
mode explicitly and configures Python function duration conservatively. Add
`[tool.vercel] entrypoint = "app:app"` if required by the current Vercel Python
runtime. Ensure static and JSON fixture files are included in the deployment
bundle.

- [ ] **Step 4: Verify the entry point and local server**

Run: `TRANSIT_APP_MODE=demo uv run python -c 'from app import app; print(app.title)'`

Run: `uv run pytest tests/web/test_vercel_entrypoint.py tests/web -q`

- [ ] **Step 5: Run a local HTTP smoke check**

Start `TRANSIT_APP_MODE=demo uv run uvicorn app:app --port 8765`, request `/`,
`/api/health`, `/api/ready`, `/api/stops/search?q=central`, `/api/arrivals`, and
`/api/accuracy`, then terminate the server. Assert expected HTTP statuses and
demo labels.

- [ ] **Step 6: Commit**

```bash
git add app.py vercel.json pyproject.toml .gitignore tests/web/test_vercel_entrypoint.py
git commit -m "feat(deploy): add Vercel demo entry point"
```

---

### Task 5: PostgreSQL engine and reliability upserts

**Files:**
- Create: `src/umich_transit/core/storage/upsert.py`
- Modify: `src/umich_transit/core/storage/db.py`
- Modify: `src/umich_transit/poller/stats_job.py`
- Modify: `pyproject.toml`
- Test: `tests/core/storage/test_db.py`
- Create: `tests/core/storage/test_upsert.py`

**Interfaces:**
- Produces: `normalize_database_url(url: str) -> str`
- Produces: `build_reliability_upsert(dialect_name: str, values: Mapping[str, Any]) -> Executable`
- Consumes: existing `ReliabilityStat` table and stats-job values

- [ ] **Step 1: Write failing URL-normalization tests**

```python
@pytest.mark.parametrize(("raw", "expected"), [
    ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("sqlite:///data/test.db", "sqlite:///data/test.db"),
])
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected
```

- [ ] **Step 2: Run URL tests and verify RED**

Run: `uv run pytest tests/core/storage/test_db.py -q`

- [ ] **Step 3: Implement normalization and psycopg dependency**

Call the normalizer inside `create_engine_for_url`. Add
`psycopg[binary]>=3.2` to project dependencies and refresh `uv.lock`.

- [ ] **Step 4: Run URL tests and verify GREEN**

- [ ] **Step 5: Write failing dialect-upsert compilation tests**

Build one statement for `sqlite` and one for `postgresql`, compile each with the
matching SQLAlchemy dialect, and assert both use `ON CONFLICT` over
`route_id, stop_id, dow, hour` and update all derived metrics.

- [ ] **Step 6: Run upsert tests and verify RED**

Run: `uv run pytest tests/core/storage/test_upsert.py -q`

- [ ] **Step 7: Implement the dialect helper and refactor the stats job**

Reject unsupported dialects with a clear `ValueError`. Do not change the stats
calculation or transaction boundaries.

- [ ] **Step 8: Run storage and poller tests, then commit**

Run: `uv run pytest tests/core/storage tests/poller/test_stats_job.py -q`

```bash
git add pyproject.toml uv.lock src/umich_transit/core/storage src/umich_transit/poller/stats_job.py tests/core/storage
git commit -m "feat(storage): support PostgreSQL reliability writes"
```

---

### Task 6: Safe SQLite-to-PostgreSQL migration command

**Files:**
- Create: `src/umich_transit/core/storage/copy_database.py`
- Create: `scripts/migrate_database.py`
- Test: `tests/core/storage/test_copy_database.py`

**Interfaces:**
- Produces: `copy_database(source: Engine, destination: Engine, *, replace: bool = False) -> dict[str, int]`
- Produces CLI: `python scripts/migrate_database.py --source-url ... --destination-url ... [--replace]`

- [ ] **Step 1: Write failing copy tests**

Create two temporary SQLite engines as portable stand-ins. Seed routes, stops,
route-stops, predictions, arrivals, reliability stats, and parse errors in the
source. Assert an empty destination receives identical per-table counts, the
source remains unchanged, and a second copy refuses the non-empty destination.

- [ ] **Step 2: Run copy tests and verify RED**

Run: `uv run pytest tests/core/storage/test_copy_database.py -q`

- [ ] **Step 3: Implement dependency-ordered copying**

Use `Base.metadata.sorted_tables` for inserts and reverse order for explicit
replacement deletes. Run the entire destination mutation in one transaction.
Return verified destination counts and raise if any copied count differs.

- [ ] **Step 4: Run copy tests and verify GREEN**

- [ ] **Step 5: Add failing CLI-validation tests**

Assert identical source/destination URLs are rejected, missing schemes are
rejected, and `--replace` is required for a populated destination. The CLI must
print table counts without printing credentials; redact passwords in errors.

- [ ] **Step 6: Implement CLI validation and verify**

Run: `uv run pytest tests/core/storage/test_copy_database.py -q`

- [ ] **Step 7: Commit**

```bash
git add src/umich_transit/core/storage/copy_database.py scripts/migrate_database.py tests/core/storage/test_copy_database.py
git commit -m "feat(storage): add safe database migration command"
```

---

### Task 7: Documentation, full verification, and Vercel deployment

**Files:**
- Modify: `README.md`
- Modify: `docs/DEPLOY.md`
- Create: `scripts/smoke_public_demo.py`
- Test: `tests/web/test_smoke_script.py`

**Interfaces:**
- Produces: `uv run python scripts/smoke_public_demo.py --base-url <url>`
- Produces: generated Vercel deployment URL

- [ ] **Step 1: Write a failing smoke-script contract test**

Use an in-process test server or injected HTTP transport. Assert the script
checks `/`, `/api/health`, `/api/ready`, stop search, arrivals, accuracy, static
CSS, demo labels, and GitHub/methodology links, and returns nonzero on a failed
check.

- [ ] **Step 2: Run the smoke test and verify RED**

Run: `uv run pytest tests/web/test_smoke_script.py -q`

- [ ] **Step 3: Implement the smoke script and documentation**

Update the README around the public outcome, but do not add a live-demo link
until a production URL exists. Update `docs/DEPLOY.md` with Vercel web versus
worker responsibilities, demo/live variables, PostgreSQL migration, rollback,
and later domain attachment. Update the README test badge to the current
verified count.

- [ ] **Step 4: Run the complete local verification gate**

Run: `uv run pytest --cov=umich_transit --cov-report=term-missing`

Run: `uv run ruff check .`

Run: `uv run mypy src app.py scripts/migrate_database.py scripts/smoke_public_demo.py`

Run: `TRANSIT_APP_MODE=demo uv run python scripts/smoke_public_demo.py --local`

- [ ] **Step 5: Commit the verified documentation and smoke tooling**

```bash
git add README.md docs/DEPLOY.md scripts/smoke_public_demo.py tests/web/test_smoke_script.py
git commit -m "docs: add public demo deployment workflow"
```

- [ ] **Step 6: Deploy to Vercel**

Use the connected Vercel capability when available; otherwise use an already
authenticated Vercel CLI. Create a preview deployment first, inspect build logs,
run the smoke script against it, then promote the exact verified deployment to
production. Do not configure a custom domain in this task.

- [ ] **Step 7: Verify production and update the live link**

Run the smoke script against the production `*.vercel.app` URL. Add that exact
URL to the README, rerun documentation and smoke tests, commit, push if
authorized and required for deployment, and report the URL.
