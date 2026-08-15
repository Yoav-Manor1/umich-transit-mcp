# U-Mich Transit Web Dashboard — Design

**Date:** 2026-06-03
**Status:** Draft for review
**Author:** Yoav Manor

## Pitch

A small local web page that shows U-M bus arrivals at a glance and tells you
exactly **when to leave** to catch your bus. No chat, no commands: run one
command, a browser opens, you see your buses. It reuses the existing `core/`
service — the same logic behind the MCP tools and the poller — through a thin
FastAPI HTTP layer. This is the *"FastAPI HTTP layer over the same `core/`"*
already on the README roadmap, now built.

## Goals

1. **"See it myself."** A glanceable page the user opens in a browser on their
   Mac, with no assistant in the loop.
2. **Answer "when do I leave?" directly** via a walk-time-aware countdown banner.
3. **Multiple saved stops** with search and one-click switching.
4. **Zero duplicated bus logic.** Reuse `TransitService`; no DB schema changes.
5. **Grows into a phone version later** with essentially one host/bind change.

## Non-goals (v1)

- Phone / remote hosting. Documented as the natural next step, not built now.
- Trip planner (A→B) in the UI. The service has `plan_trip`; deferred from the page.
- Reliability heatmaps / charts.
- User accounts or server-side persistence. Favorites live in the browser.
- Auth, multi-user, and any write/mutating operations. Read-only, localhost-only.

## Audience and stack

- **FastAPI + uvicorn** — async, matching the async `core/` and `httpx` client.
- **Server-rendered single page + vanilla JS** — no Node, no build step.
- Reuses `TransitService`, `MbusClient`, and the SQLAlchemy engine **exactly as
  the MCP server constructs them** (see Wiring).
- **Browser `localStorage`** for favorites and per-stop walk time.
- New deps: `fastapi`, `uvicorn[standard]`.

## Architecture

The web server is a third **on-demand process** beside the MCP server. Both
share `core/` and the SQLite DB; neither touches the poller. The README's
"future" HTTP/Frontend box is now this layer.

```
┌────────────────┐   ┌────────────────┐
│  MCP Server    │   │  Web Dashboard │   ← this project
│  (stdio, thin) │   │  (FastAPI)     │
└────────┬───────┘   └────────┬───────┘
         │                    │
         ▼                    ▼
┌──────────────────────────────────────┐
│  umich_transit.core                  │
│    clients/  storage/  reliability/  │
│    planner/  service/  (TransitService)
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  SQLite (WAL)  ◄── Background Poller  │
└──────────────────────────────────────┘
```

### Boundary rules (same as the rest of the project)

1. `web/` never imports from `mcp_server/` or `poller/`.
2. Route handlers contain no SQL and no HTTP-client code — they call
   `TransitService` (and `leave.py`) and format the result, mirroring how
   `mcp_server/tools.py` stays thin.
3. The "when to leave" math lives in one pure, unit-tested function.

## Repo layout (new files)

```
src/umich_transit/web/
├── __init__.py
├── __main__.py        # entry point: uvicorn + optional browser auto-open
├── app.py             # build_app() -> FastAPI; lifespan wires TransitService
├── leave.py           # compute_leave(): pure, tested "when to leave" math
└── static/
    ├── index.html     # the page (markup)
    ├── app.js         # fetch + render + 20s refresh + favorites/search
    └── style.css
tests/web/
├── test_leave.py      # leave-in math (TDD, written first)
└── test_api.py        # endpoint tests via FastAPI TestClient
```

New entry point in `pyproject.toml`:

```toml
[project.scripts]
umich-transit-web = "umich_transit.web.__main__:main"
```

## Wiring (mirror `build_server`)

`build_app()` returns a `FastAPI` whose **lifespan** constructs the same objects
`mcp_server/server.py:build_server()` builds today, and closes the HTTP client on
shutdown:

```python
# app.py (sketch)
@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = create_engine_for_url(settings.database_url)
    http = httpx.AsyncClient(timeout=15.0)
    mbus = MbusClient(base_url=settings.mbus_base_url,
                      api_key=settings.mbus_api_key.get_secret_value(), http=http)
    app.state.svc = TransitService(engine=engine, mbus=mbus)
    try:
        yield
    finally:
        await http.aclose()
```

Same `settings`, same relative-DB resolution (`uv run umich-transit-web` from the
project root, exactly like the poller and MCP server).

## HTTP API

| Method / path | Calls | Returns |
|---|---|---|
| `GET /` | — | `static/index.html` |
| `GET /static/*` | — | JS/CSS assets |
| `GET /api/stops/search?q=&limit=8` | `svc.find_stops(query=q, limit=limit)` | `{stops: [{id, name, lat, lon, agency}]}` |
| `GET /api/arrivals?stop_id=&walk_min=5&limit=5` | `svc.get_arrivals(stop_id=…, limit=…)` + `compute_leave(...)` | `{stop_id, now, updated_at, arrivals: [...], leave: {…} \| null}` |

`arrivals[]` passes the service shape straight through: `route_id`,
`predicted_arrival_at`, `adjusted_arrival_at`, `confidence`,
`on_time_pct_at_this_hour`, `sample_size`, `vehicle_id` (ISO timestamps). The
response also includes a server `now` so the client can tick the "min" counts
between refetches without clock skew.

## When-to-leave logic (`leave.py` — pure + tested)

```
effective_eta(item) = adjusted_arrival_at if confidence == "high"
                      else predicted_arrival_at      # mirrors get_arrivals_tool
```

```
compute_leave(arrivals, walk_min, now) -> dict | None:
    upcoming = [a for a in arrivals if effective_eta(a) >= now]
    if not upcoming: return None
    target = min(upcoming, key=effective_eta)        # soonest catchable bus
    minutes_until = ceil((effective_eta(target) - now) / 60s)
    leave_in_min  = max(0, minutes_until - walk_min)
    return {leave_in_min, route_id, arrival_at: effective_eta(target), confidence}
```

`leave_in_min == 0` renders as **"Leave now."** `walk_min` defaults to **5** when
a stop has no configured walk time. This function is the single source of truth
for the green banner and is written test-first.

## Frontend behavior (vanilla JS)

- **`localStorage`**: `favorites = [{stop_id, name, walk_min}]`, `selected_stop_id`.
- **On load**: render favorite chips → select last-used (or first) → fetch
  `/api/arrivals` → render board + banner → start a 20s refresh interval; also
  refresh on window focus.
- **Search**: debounced input → `/api/stops/search` → result list → clicking a
  result adds it to favorites (prompt for walk time, default 5) and selects it.
- **Chip**: click to select; small ✎ to edit walk time, ✕ to remove.
- **Board row**: route color dot + name, ETA in minutes, clock time, and a
  `live` badge (becomes the confidence label once `confidence == "high"`).
- **Banner**: green "Leave in N min to catch `<route>` at `<time>`", or "Leave
  now" at 0; hidden when there are no arrivals.
- **Empty state** (no favorites): a welcome panel prompting a first search.

## Error handling

| Failure | Behavior |
|---|---|
| Magic Bus unreachable / 5xx / timeout | `/api/arrivals` catches the client error and returns `{arrivals: [], leave: null, error: "upstream"}` with HTTP 200. Frontend keeps the last good board and shows a subtle "couldn't refresh — retrying" note. |
| No upcoming arrivals | `arrivals: []`, `leave: null`; board shows a friendly empty message, banner hidden. |
| Missing / unknown `stop_id` | `400` with a message; frontend clears the board. |
| No favorites yet | Welcome / empty state. |
| Walk time unset for a stop | Default 5 min; hint to set it. |
| SQLite locked | Inherited WAL behavior; the web layer only reads. |

## Testing strategy

- **`tests/web/test_leave.py`** (written first, TDD): walk < ETA → positive
  countdown; walk ≥ ETA → `0` ("leave now"); empty arrivals → `None`; picks the
  soonest catchable bus; high-confidence target uses `adjusted_arrival_at`. Pure,
  no IO.
- **`tests/web/test_api.py`**: FastAPI `TestClient` with a seeded test engine and
  an `respx`-mocked `MbusClient` (following the existing client-test pattern).
  Assert `/api/stops/search` returns stops, `/api/arrivals` returns the board +
  `leave` object, and the upstream-error path degrades to a graceful empty body.
- **Manual smoke**: `uv run umich-transit-web`, open the browser, search a stop,
  add it, confirm the board refreshes and the leave banner counts down.
- No JS test framework in v1 — the frontend is deliberately thin so the tested
  logic lives in Python.

## Launch / UX

- `uv run umich-transit-web` → uvicorn on **127.0.0.1:8000** (localhost only, not
  exposed). `main()` optionally calls `webbrowser.open("http://localhost:8000")`
  shortly after start so the page just appears.
- README gains a short **"Web dashboard"** section beside the MCP/poller
  quickstart.

## Sequencing (for the implementation plan)

1. Add deps (`fastapi`, `uvicorn[standard]`), `web/` skeleton, entry point.
2. `leave.py` + `test_leave.py` (TDD — the algorithmic core of the banner).
3. `app.py` `build_app()` + lifespan wiring + `/api/*` endpoints + `test_api.py`.
4. `static/` page: `index.html`, `style.css`, `app.js` (board + 20s refresh).
5. Favorites + search + walk-time editing (`localStorage`).
6. Wire the green when-to-leave banner to the `leave` object.
7. Error and empty states.
8. `__main__` launch + browser auto-open; README "Web dashboard" section.

## Future (explicitly deferred)

- **Phone access**: bind `0.0.0.0` behind the existing Docker/host (plus a light
  access control). The single biggest follow-up, and intentionally small.
- **Trip planner panel** — the service already exposes `plan_trip`.
- **Reliability detail / charts** per route or stop.
- **Server-side favorites** once multi-device sync matters.
