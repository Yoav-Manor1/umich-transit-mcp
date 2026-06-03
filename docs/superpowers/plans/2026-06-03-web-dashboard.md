# Web Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web page (`uv run umich-transit-web`) that shows live U-M bus arrivals for searchable, saved stops and tells the user when to leave, reusing the existing `core/` service.

**Architecture:** A thin FastAPI app wraps the existing `TransitService` (same wiring as `mcp_server/server.py`). It serves one static HTML/JS page plus two JSON endpoints (`/api/stops/search`, `/api/arrivals`). The "when to leave" math is one pure, unit-tested function. Favorites and per-stop walk times live in browser `localStorage`; no DB schema changes.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, the existing SQLAlchemy/`httpx`/`TransitService` core, vanilla JS/CSS frontend. Tests with `pytest` + FastAPI `TestClient` + `unittest.mock.AsyncMock`.

---

## File Structure

**Create:**
- `src/umich_transit/web/__init__.py` — empty package marker.
- `src/umich_transit/web/leave.py` — `compute_leave()`: pure "when to leave" math (the only non-trivial logic; fully unit-tested).
- `src/umich_transit/web/app.py` — `build_app()`: FastAPI factory, lifespan wiring (mirrors `build_server`), `/api/*` endpoints, static mount. Injectable service for tests.
- `src/umich_transit/web/__main__.py` — `main()`: launch uvicorn + auto-open the browser.
- `src/umich_transit/web/static/index.html` — page markup.
- `src/umich_transit/web/static/style.css` — styling.
- `src/umich_transit/web/static/app.js` — fetch + render + 20s refresh + search + favorites + walk-time + banner.
- `tests/web/__init__.py` — empty package marker.
- `tests/web/test_leave.py` — unit tests for `compute_leave`.
- `tests/web/test_api.py` — endpoint tests via `TestClient`.

**Modify:**
- `pyproject.toml` — add `fastapi` + `uvicorn[standard]` deps and the `umich-transit-web` script entry.
- `README.md` — add a "Web dashboard" section.

**Responsibility boundaries:** `app.py` only formats requests/responses and calls `TransitService` + `compute_leave` (no SQL, no HTTP-client code — same rule as `mcp_server/tools.py`). `leave.py` is pure (no IO). The frontend is deliberately thin so all tested logic stays in Python.

---

### Task 1: Web package scaffold, dependencies, and app skeleton

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Create: `src/umich_transit/web/__init__.py`
- Create: `src/umich_transit/web/app.py`
- Create: `tests/web/__init__.py`
- Test: `tests/web/test_api.py` (health check only in this task)

- [ ] **Step 1: Add the web dependencies**

Run:
```bash
uv add fastapi "uvicorn[standard]"
```
Expected: `pyproject.toml` gains `fastapi` and `uvicorn[standard]` under `[project.dependencies]`, and `uv.lock` updates.

- [ ] **Step 2: Create the empty package markers**

Create `src/umich_transit/web/__init__.py` with a single line:
```python
"""Local web dashboard (FastAPI) over the shared core service."""
```

Create `tests/web/__init__.py` as an empty file:
```python
```

- [ ] **Step 3: Write the failing test (health endpoint)**

Create `tests/web/test_api.py`:
```python
"""Tests for the web dashboard HTTP endpoints."""
from fastapi.testclient import TestClient

from umich_transit.web.app import build_app


def test_health_ok():
    client = TestClient(build_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/web/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'umich_transit.web.app'`.

- [ ] **Step 5: Write the minimal app**

Create `src/umich_transit/web/app.py`:
```python
"""FastAPI app factory for the local bus dashboard.

Wiring mirrors mcp_server/server.py:build_server() — the same engine, httpx
client, MbusClient, and TransitService. Pass `svc` to inject a service in
tests; otherwise the lifespan builds one from settings and closes the HTTP
client on shutdown.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from umich_transit.config import settings
from umich_transit.core.clients.mbus import MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url


def build_app(svc: TransitService | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if getattr(app.state, "svc", None) is None:
            engine = create_engine_for_url(settings.database_url)
            http = httpx.AsyncClient(timeout=15.0)
            mbus = MbusClient(
                base_url=settings.mbus_base_url,
                api_key=settings.mbus_api_key.get_secret_value(),
                http=http,
            )
            app.state.svc = TransitService(engine=engine, mbus=mbus)
            app.state.http = http
        try:
            yield
        finally:
            http_client = getattr(app.state, "http", None)
            if http_client is not None:
                await http_client.aclose()

    app = FastAPI(title="U-Mich Transit Dashboard", lifespan=lifespan)
    app.state.svc = svc
    app.state.http = None

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/web/test_api.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/umich_transit/web/__init__.py src/umich_transit/web/app.py tests/web/__init__.py tests/web/test_api.py
git commit -m "feat(web): scaffold FastAPI dashboard app with health endpoint"
```

---

### Task 2: The "when to leave" function

**Files:**
- Create: `src/umich_transit/web/leave.py`
- Test: `tests/web/test_leave.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/web/test_leave.py`:
```python
"""Unit tests for the when-to-leave computation."""
from datetime import UTC, datetime, timedelta

from umich_transit.web.leave import compute_leave

NOW = datetime(2026, 6, 3, 17, 0, tzinfo=UTC)


def _eta(minutes, route="CN", confidence="low", adj_minutes=None):
    pred = NOW + timedelta(minutes=minutes)
    adj = NOW + timedelta(minutes=adj_minutes) if adj_minutes is not None else pred
    return {
        "route_id": route,
        "predicted_arrival_at": pred,
        "adjusted_arrival_at": adj,
        "confidence": confidence,
    }


def test_returns_none_when_no_arrivals():
    assert compute_leave([], walk_min=5, now=NOW) is None


def test_counts_down_when_walk_less_than_eta():
    res = compute_leave([_eta(10)], walk_min=4, now=NOW)
    assert res is not None
    assert res["leave_in_min"] == 6
    assert res["route_id"] == "CN"


def test_leave_now_when_walk_exceeds_eta():
    res = compute_leave([_eta(3)], walk_min=5, now=NOW)
    assert res is not None
    assert res["leave_in_min"] == 0


def test_picks_soonest_bus():
    res = compute_leave([_eta(12, route="CS"), _eta(6, route="CN")], walk_min=2, now=NOW)
    assert res is not None
    assert res["route_id"] == "CN"
    assert res["leave_in_min"] == 4


def test_uses_adjusted_eta_when_high_confidence():
    # published 6 min, but history says 12; high confidence -> plan for 12
    res = compute_leave(
        [_eta(6, confidence="high", adj_minutes=12)], walk_min=2, now=NOW
    )
    assert res is not None
    assert res["leave_in_min"] == 10
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_leave.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'umich_transit.web.leave'`.

- [ ] **Step 3: Write the implementation**

Create `src/umich_transit/web/leave.py`:
```python
"""Pure 'when should I leave?' computation for the dashboard banner.

Given the arrivals dicts returned by TransitService.get_arrivals (which carry
both a published and a reliability-adjusted ETA plus a confidence label) and the
user's walk time to the stop, decide when to leave for the soonest catchable bus.
"""
from datetime import datetime
from math import ceil
from typing import Any


def _effective_eta(item: dict[str, Any]) -> datetime:
    """Use the adjusted ETA only when we trust it (high confidence), else the
    published one — the same convention as mcp_server/tools.get_arrivals_tool."""
    key = "adjusted_arrival_at" if item.get("confidence") == "high" else "predicted_arrival_at"
    eta = item[key]
    assert isinstance(eta, datetime)
    return eta


def compute_leave(
    arrivals: list[dict[str, Any]], walk_min: int, now: datetime
) -> dict[str, Any] | None:
    """Return the leave-now banner data, or None if there is no upcoming bus."""
    upcoming = [a for a in arrivals if _effective_eta(a) >= now]
    if not upcoming:
        return None
    target = min(upcoming, key=_effective_eta)
    eta = _effective_eta(target)
    minutes_until = ceil((eta - now).total_seconds() / 60)
    leave_in_min = max(0, minutes_until - walk_min)
    return {
        "leave_in_min": leave_in_min,
        "minutes_until": minutes_until,
        "route_id": target["route_id"],
        "arrival_at": eta.isoformat(),
        "confidence": target.get("confidence", "low"),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_leave.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/web/leave.py tests/web/test_leave.py
git commit -m "feat(web): add pure when-to-leave computation with tests"
```

---

### Task 3: Search and arrivals endpoints

**Files:**
- Modify: `src/umich_transit/web/app.py`
- Test: `tests/web/test_api.py`

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/web/test_api.py` with:
```python
"""Tests for the web dashboard HTTP endpoints."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from umich_transit.core.clients.base import EtaRecord
from umich_transit.core.clients.mbus import BusTimeError
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url, session_scope
from umich_transit.core.storage.models import Base, Route, Stop
from umich_transit.web.app import build_app


def _service(etas=None, raise_upstream=False):
    engine = create_engine_for_url("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with session_scope(engine) as s:
        s.add(Route(id="CN", agency="mbus", short_name="CN", long_name="Commuter North"))
        s.add(Stop(id="C251", agency="mbus",
                   name="Central Campus Transit Center", lat=42.27, lon=-83.73))
    mbus = AsyncMock()
    if raise_upstream:
        mbus.get_etas = AsyncMock(side_effect=BusTimeError("bad key"))
    else:
        mbus.get_etas = AsyncMock(return_value=etas or [])
    return TransitService(engine=engine, mbus=mbus)


def test_health_ok():
    client = TestClient(build_app(_service()))
    assert client.get("/api/health").json() == {"status": "ok"}


def test_search_returns_matching_stops():
    client = TestClient(build_app(_service()))
    r = client.get("/api/stops/search", params={"q": "central"})
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["stops"]]
    assert "Central Campus Transit Center" in names


def test_arrivals_returns_board_and_leave():
    eta_at = datetime.now(UTC) + timedelta(minutes=6)
    etas = [EtaRecord(route_id="CN", stop_id="C251", vehicle_id="v1",
                      predicted_arrival_at=eta_at, captured_at=datetime.now(UTC))]
    client = TestClient(build_app(_service(etas)))
    r = client.get("/api/arrivals", params={"stop_id": "C251", "walk_min": 2})
    body = r.json()
    assert r.status_code == 200
    assert len(body["arrivals"]) == 1
    assert body["arrivals"][0]["route_id"] == "CN"
    assert body["leave"]["route_id"] == "CN"
    assert body["leave"]["leave_in_min"] in (3, 4)  # ~6 min ETA minus 2 min walk


def test_arrivals_degrades_gracefully_on_upstream_error():
    client = TestClient(build_app(_service(raise_upstream=True)))
    r = client.get("/api/arrivals", params={"stop_id": "C251"})
    body = r.json()
    assert r.status_code == 200
    assert body["arrivals"] == []
    assert body["leave"] is None
    assert body["error"] == "upstream"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/web/test_api.py -v`
Expected: FAIL — `test_search_returns_matching_stops` and the two arrivals tests fail with 404 (endpoints not defined yet). `test_health_ok` passes.

- [ ] **Step 3: Add the endpoints to `app.py`**

In `src/umich_transit/web/app.py`, update the imports at the top of the file to:
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, Request

from umich_transit.config import settings
from umich_transit.core.clients.mbus import BusTimeError, MbusClient
from umich_transit.core.service import TransitService
from umich_transit.core.storage.db import create_engine_for_url
from umich_transit.web.leave import compute_leave
```

Then, inside `build_app`, immediately after the existing `health` route, add:
```python
    @app.get("/api/stops/search")
    def search_stops(request: Request, q: str = "", limit: int = 8) -> dict[str, Any]:
        svc: TransitService = request.app.state.svc
        return {"stops": svc.find_stops(query=q, limit=limit)}

    @app.get("/api/arrivals")
    async def arrivals(
        request: Request, stop_id: str, walk_min: int = 5, limit: int = 5
    ) -> dict[str, Any]:
        svc: TransitService = request.app.state.svc
        now = datetime.now(UTC)
        try:
            items = await svc.get_arrivals(stop_id=stop_id, limit=limit)
        except (httpx.HTTPError, BusTimeError):
            return {
                "stop_id": stop_id, "now": now.isoformat(),
                "arrivals": [], "leave": None, "error": "upstream",
            }
        return {
            "stop_id": stop_id,
            "now": now.isoformat(),
            "arrivals": items,
            "leave": compute_leave(items, walk_min, now),
        }
```

(FastAPI's response encoder converts the `datetime` values inside `items` to ISO strings automatically.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/web/test_api.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/umich_transit/web/app.py tests/web/test_api.py
git commit -m "feat(web): add stop-search and arrivals endpoints with leave banner"
```

---

### Task 4: Frontend page (static HTML/CSS/JS)

**Files:**
- Create: `src/umich_transit/web/static/index.html`
- Create: `src/umich_transit/web/static/style.css`
- Create: `src/umich_transit/web/static/app.js`
- Modify: `src/umich_transit/web/app.py` (mount static + serve index)

- [ ] **Step 1: Create the HTML page**

Create `src/umich_transit/web/static/index.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>U-M Buses</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <div class="app">
    <header class="topbar">
      <span class="brand">🚌 U-M Buses</span>
      <span id="updated" class="updated"></span>
    </header>

    <div class="search-wrap">
      <input id="search" class="search" autocomplete="off"
             placeholder="Search a stop to add… (e.g. Pierpont)">
      <div id="results" class="results"></div>
    </div>

    <div id="chips" class="chips"></div>
    <div id="note" class="note" style="display:none"></div>

    <div id="empty" class="empty" style="display:none">
      <p>No stops yet.<br>Search above to add your first stop.</p>
    </div>

    <div id="board" class="board" style="display:none">
      <div class="stop-head">
        <span id="stop-name" class="stop-name"></span>
        <span id="walk-label" class="walk"></span>
      </div>
      <div id="banner" class="banner" style="display:none">
        <span class="banner-ico">⏱️</span>
        <div>
          <div class="banner-main"></div>
          <div class="banner-sub"></div>
        </div>
      </div>
      <div id="arrivals" class="arrivals"></div>
      <div class="foot">↻ Auto-updates every 20 sec</div>
    </div>
  </div>
  <script src="/static/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create the stylesheet**

Create `src/umich_transit/web/static/style.css`:
```css
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, system-ui, sans-serif;
       background: #eceef3; color: #1a1a1a; }
.app { max-width: 560px; margin: 24px auto; background: #fff; border-radius: 12px;
       overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,.1); }
.topbar { background: #00274c; color: #fff; padding: 14px 18px;
          display: flex; justify-content: space-between; align-items: center; }
.brand { font-weight: 700; }
.updated { font-size: 12px; opacity: .8; }
.search-wrap { padding: 14px 18px 6px; position: relative; }
.search { width: 100%; padding: 10px 12px; border: 1px solid #dfe3ea;
          border-radius: 8px; font-size: 14px; }
.results { position: absolute; left: 18px; right: 18px; background: #fff;
           border: 1px solid #e3e6ec; border-radius: 8px; margin-top: 4px;
           z-index: 5; box-shadow: 0 6px 18px rgba(0,0,0,.12); }
.result { padding: 10px 12px; cursor: pointer; font-size: 14px; }
.result:hover { background: #f1f4f9; }
.chips { display: flex; gap: 8px; flex-wrap: wrap; padding: 6px 18px 12px;
         border-bottom: 1px solid #eee; }
.chip { background: #eef0f4; color: #333; padding: 6px 10px; border-radius: 14px;
        font-size: 13px; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.chip.active { background: #00274c; color: #fff; }
.chip-x { border: none; background: transparent; color: inherit; cursor: pointer;
          font-size: 14px; line-height: 1; padding: 0; }
.note { background: #fff7e6; color: #8a5b00; padding: 8px 18px; font-size: 13px; }
.empty { padding: 40px 18px; text-align: center; color: #6a7180; }
.stop-head { display: flex; justify-content: space-between; align-items: baseline;
             padding: 14px 18px 4px; }
.stop-name { font-weight: 700; font-size: 15px; }
.walk { font-size: 12px; color: #6a7180; }
.banner { margin: 6px 18px; background: #e6f6ec; border: 1px solid #cfe9d8;
          border-radius: 8px; padding: 12px 14px; display: flex; gap: 10px; align-items: center; }
.banner-ico { font-size: 22px; }
.banner-main { font-weight: 700; color: #1b7a3d; font-size: 16px; }
.banner-sub { color: #3a6b4c; font-size: 12px; }
.arrivals { padding: 6px 18px 12px; }
.row { display: flex; justify-content: space-between; align-items: center;
       padding: 10px 0; border-bottom: 1px solid #eee; }
.row:last-child { border-bottom: none; }
.route { font-weight: 600; }
.right { display: flex; gap: 10px; align-items: center; }
.clock { color: #888; font-size: 12px; }
.eta { font-size: 15px; }
.badge { background: #eef; color: #3355cc; font-size: 10px; padding: 2px 6px; border-radius: 4px; }
.muted { color: #8a8f99; padding: 14px 0; }
.foot { background: #f7f8fa; padding: 9px 18px; color: #8a8f99; font-size: 11px; }
```

- [ ] **Step 3: Create the frontend script**

Create `src/umich_transit/web/static/app.js`:
```javascript
const LS_FAVS = "umt_favorites";
const LS_SEL = "umt_selected";
let refreshTimer = null;
let searchTimer = null;

function loadFavs() {
  try { return JSON.parse(localStorage.getItem(LS_FAVS)) || []; }
  catch { return []; }
}
function saveFavs(favs) { localStorage.setItem(LS_FAVS, JSON.stringify(favs)); }
function getSelected() { return localStorage.getItem(LS_SEL); }
function setSelected(id) { localStorage.setItem(LS_SEL, id); }

function fmtClock(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function minsUntil(iso, nowIso) {
  return Math.max(0, Math.ceil((new Date(iso) - new Date(nowIso)) / 60000));
}

async function api(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => url.searchParams.set(k, v));
  const r = await fetch(url);
  return r.json();
}

function currentWalk() {
  const f = loadFavs().find((x) => x.stop_id === getSelected());
  return f ? f.walk_min : 5;
}

function renderChips() {
  const favs = loadFavs();
  const sel = getSelected();
  const el = document.getElementById("chips");
  el.innerHTML = "";
  favs.forEach((f) => {
    const chip = document.createElement("span");
    chip.className = "chip" + (f.stop_id === sel ? " active" : "");
    chip.textContent = f.name;
    chip.onclick = () => { setSelected(f.stop_id); renderChips(); refresh(); };
    const x = document.createElement("button");
    x.className = "chip-x";
    x.textContent = "×";
    x.onclick = (e) => { e.stopPropagation(); removeFav(f.stop_id); };
    chip.appendChild(x);
    el.appendChild(chip);
  });
}

function removeFav(id) {
  const favs = loadFavs().filter((f) => f.stop_id !== id);
  saveFavs(favs);
  if (getSelected() === id) {
    if (favs.length) setSelected(favs[0].stop_id);
    else localStorage.removeItem(LS_SEL);
  }
  renderChips();
  refresh();
}

function addFav(stop) {
  const favs = loadFavs();
  if (!favs.some((f) => f.stop_id === stop.id)) {
    const raw = prompt(`Minutes to walk to "${stop.name}"?`, "5");
    const walk = parseInt(raw, 10);
    favs.push({ stop_id: stop.id, name: stop.name, walk_min: isNaN(walk) ? 5 : walk });
    saveFavs(favs);
  }
  setSelected(stop.id);
  document.getElementById("search").value = "";
  document.getElementById("results").innerHTML = "";
  renderChips();
  refresh();
}

function onSearch(e) {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  const box = document.getElementById("results");
  if (!q) { box.innerHTML = ""; return; }
  searchTimer = setTimeout(async () => {
    const data = await api("/api/stops/search", { q, limit: 8 });
    box.innerHTML = "";
    (data.stops || []).forEach((s) => {
      const item = document.createElement("div");
      item.className = "result";
      item.textContent = s.name;
      item.onclick = () => addFav(s);
      box.appendChild(item);
    });
  }, 250);
}

function setNote(text) {
  const n = document.getElementById("note");
  n.textContent = text;
  n.style.display = text ? "block" : "none";
}

function renderBanner(leave) {
  const b = document.getElementById("banner");
  if (!leave) { b.style.display = "none"; return; }
  b.style.display = "flex";
  b.querySelector(".banner-main").textContent =
    leave.leave_in_min <= 0 ? "Leave now" : `Leave in ${leave.leave_in_min} min`;
  b.querySelector(".banner-sub").textContent =
    `to catch ${leave.route_id} (arrives ${fmtClock(leave.arrival_at)})`;
}

function renderArrivals(arrivals, nowIso) {
  const list = document.getElementById("arrivals");
  list.innerHTML = "";
  if (!arrivals.length) {
    list.innerHTML = '<div class="muted">No upcoming arrivals right now.</div>';
    return;
  }
  arrivals.forEach((a) => {
    const etaIso = a.confidence === "high" ? a.adjusted_arrival_at : a.predicted_arrival_at;
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML =
      `<span class="route">${a.route_id}</span>` +
      `<span class="right">` +
      `<span class="clock">${fmtClock(a.predicted_arrival_at)}</span>` +
      `<b class="eta">${minsUntil(etaIso, nowIso)} min</b>` +
      `<span class="badge">${a.confidence === "high" ? "history" : "live"}</span>` +
      `</span>`;
    list.appendChild(row);
  });
}

async function refresh() {
  const sel = getSelected();
  const empty = document.getElementById("empty");
  const board = document.getElementById("board");
  if (!sel) { empty.style.display = "block"; board.style.display = "none"; return; }
  empty.style.display = "none";
  board.style.display = "block";

  let data;
  try {
    data = await api("/api/arrivals", { stop_id: sel, walk_min: currentWalk(), limit: 5 });
  } catch {
    setNote("Couldn't refresh — retrying…");
    return;
  }
  setNote(data.error ? "Couldn't reach the bus feed — retrying…" : "");

  const fav = loadFavs().find((x) => x.stop_id === sel);
  document.getElementById("stop-name").textContent = fav ? fav.name : sel;
  document.getElementById("walk-label").textContent = `🚶 ${currentWalk()} min walk`;
  renderBanner(data.leave);
  renderArrivals(data.arrivals || [], data.now);
  document.getElementById("updated").textContent = "Updated " + fmtClock(data.now);
}

function init() {
  document.getElementById("search").addEventListener("input", onSearch);
  const favs = loadFavs();
  if (!getSelected() && favs.length) setSelected(favs[0].stop_id);
  renderChips();
  refresh();
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refresh, 20000);
  window.addEventListener("focus", refresh);
}

document.addEventListener("DOMContentLoaded", init);
```

- [ ] **Step 4: Mount the static files and serve the page**

In `src/umich_transit/web/app.py`, add these imports to the existing import block:
```python
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

Add this module-level constant after the imports (before `build_app`):
```python
STATIC_DIR = Path(__file__).resolve().parent / "static"
```

Inside `build_app`, just before `return app`, add:
```python
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
```

- [ ] **Step 5: Verify the existing tests still pass**

Run: `uv run pytest tests/web -v`
Expected: PASS (all 9 tests — 5 leave + 4 api — still green; static mount does not break them).

- [ ] **Step 6: Manual smoke check of the page**

Run (in a separate terminal, from the project root):
```bash
uv run python -c "from umich_transit.web.app import build_app; build_app(); print('app builds with static mount OK')"
```
Expected: prints `app builds with static mount OK` (confirms `STATIC_DIR` exists and mounts).

- [ ] **Step 7: Commit**

```bash
git add src/umich_transit/web/static/index.html src/umich_transit/web/static/style.css src/umich_transit/web/static/app.js src/umich_transit/web/app.py
git commit -m "feat(web): add dashboard page (search, favorites, leave banner, board)"
```

---

### Task 5: Launch command, packaging, README, and full verification

**Files:**
- Create: `src/umich_transit/web/__main__.py`
- Modify: `pyproject.toml` (script entry)
- Modify: `README.md`

- [ ] **Step 1: Create the entry point**

Create `src/umich_transit/web/__main__.py`:
```python
"""Entry point: `umich-transit-web` — the local bus dashboard.

Starts uvicorn on localhost and opens the page in the default browser.
"""
import threading
import webbrowser

import uvicorn

from umich_transit.web.app import build_app

HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(build_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Register the script in `pyproject.toml`**

In `pyproject.toml`, under `[project.scripts]`, add the `umich-transit-web` line so the block reads:
```toml
[project.scripts]
umich-transit-mcp    = "umich_transit.mcp_server.__main__:main"
umich-transit-poller = "umich_transit.poller.__main__:main"
umich-transit-web    = "umich_transit.web.__main__:main"
```

- [ ] **Step 3: Re-sync so the new script is installed**

Run: `uv sync --all-extras`
Expected: completes without error; `umich-transit-web` becomes runnable via `uv run`.

- [ ] **Step 4: Manual smoke test of the running app**

Run (in a separate terminal, from the project root):
```bash
uv run umich-transit-web
```
Then, from another terminal, verify it serves:
```bash
curl -s http://127.0.0.1:8000/api/health
curl -s "http://127.0.0.1:8000/api/stops/search?q=central"
```
Expected: health returns `{"status":"ok"}`; search returns a JSON `stops` array including `Central Campus Transit Center` (real data from `data/transit.db`). The browser should also have opened to the page; search a stop, add it, and confirm the board and green banner render. Stop the server with Ctrl+C.

- [ ] **Step 5: Add the README section**

In `README.md`, insert the following section immediately before the `## Running it 24/7` heading:

~~~markdown
## Web dashboard (see it yourself, no chat)

Prefer a page you just glance at instead of asking Claude? Run the local
dashboard:

```bash
uv run umich-transit-web        # opens http://localhost:8000 in your browser
```

Search for a stop, save a few favorites, and the page shows live arrivals with a
green **"when to leave"** banner (set your walk time per stop). It reuses the same
`core/` service as the MCP tools and reads the same database the poller fills, so
its confidence ratings improve exactly as the historical data grows.
~~~

- [ ] **Step 6: Full verification — tests, lint, types**

Run:
```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
```
Expected: all tests pass (the previous 73 plus the 9 new web tests), `ruff` reports no errors, and `mypy` reports no issues on `src` (including the new `web/` package).

- [ ] **Step 7: Commit**

```bash
git add src/umich_transit/web/__main__.py pyproject.toml README.md
git commit -m "feat(web): add umich-transit-web launch command and docs"
```

---

## Self-Review

**1. Spec coverage** — every spec section maps to a task:
- Local web page / launch command → Task 5 (`__main__`, script, README).
- Search + favorites + switching → Task 4 (`app.js` chips/search/localStorage).
- When-to-leave banner (walk-time aware) → Task 2 (`compute_leave`) + Task 3 (endpoint) + Task 4 (`renderBanner`).
- Reuse `TransitService`, no schema change → Task 1/Task 3 wiring mirrors `build_server`; only reads.
- HTTP API (`/api/stops/search`, `/api/arrivals`) → Task 3.
- `localStorage` favorites + walk time → Task 4.
- Error/empty handling (upstream, no arrivals, no favorites) → Task 3 (upstream catch) + Task 4 (`setNote`, empty state, "No upcoming arrivals").
- Tests (endpoints + leave math) → Tasks 1–3.
- Launch + browser auto-open → Task 5.

**2. Placeholder scan** — no "TBD/TODO/handle appropriately"; every code step is complete and runnable.

**3. Type consistency** — `build_app(svc=None)` signature is consistent across Tasks 1/3/4/5; `compute_leave(arrivals, walk_min, now)` signature matches its call in Task 3; the arrivals dict keys used in JS (`route_id`, `predicted_arrival_at`, `adjusted_arrival_at`, `confidence`) match the `TransitService.get_arrivals` output verified in `core/service.py`; `EtaRecord` fields in the test match `core/clients/base.py`.
