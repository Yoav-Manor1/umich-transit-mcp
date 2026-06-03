# U-Mich Transit MCP Server — Design

**Date:** 2026-05-26
**Status:** Draft for review
**Author:** Yoav Manor

## Pitch

A Model Context Protocol server that gives Claude (and a future web app) reliable
answers about University of Michigan buses. It does not just wrap the published
Magic Bus / TheRide arrival predictions — it logs every prediction, infers actual
arrivals from GPS data, and learns the gap. The user sees both the published
estimate and an empirically adjusted one: *"Magic Bus says 4 min, but Thursdays
at 5pm this stop runs ~6 min late. Plan for ~10."*

## Goals

1. Be a useful daily tool for the author and other U-Mich students.
2. Be a strong portfolio piece: novel angle, real data work, clean architecture.
3. Stay app-ready: same core logic must serve a future HTTP API + Next.js frontend
   with no rewrite.

## Non-goals

- Multi-modal trip planning (walking + driving + cycling). Bus-focused.
- Mutating operations. Read-only server.
- Personal accounts / saved preferences in v1. Future work.
- Dining halls, course catalog, library — out of scope; possible later projects.

## Audience and stack

- Python 3.11+ (best fit for the data layer; thin MCP layer either way).
- `mcp` Python SDK for the server.
- SQLAlchemy + Alembic + SQLite for storage (swap to Postgres when the app
  layer arrives — one config change).
- `httpx` for API clients, `pydantic` for typed models.
- `uv` for dependency management.

## Architecture

Three components, two long-lived processes, one shared library.

```
┌────────────────┐   ┌────────────────┐   ┌─────────────────────┐
│  MCP Server    │   │  HTTP API      │   │  Next.js Frontend   │
│  (thin)        │   │  (future)      │   │  (future)           │
└────────┬───────┘   └────────┬───────┘   └──────────┬──────────┘
         │                    │                      │ HTTP
         ▼                    ▼                      ▼
┌──────────────────────────────────────┐
│  umich_transit.core                  │
│    clients/  storage/  reliability/  │
│    planner/  service/                │
└──────────────┬───────────────────────┘
               ▼
┌──────────────────────────────────────┐
│  SQLite (→ Postgres for app)         │
└──────────▲───────────────────────────┘
           │
┌──────────┴───────────────────────────┐
│  Background Poller                   │
│    prediction logger (30s)           │
│    arrival detector (15s)            │
│    nightly stats job                 │
└──────────────────────────────────────┘
```

### Key boundary rules

1. `core/` never imports from `mcp_server/` or `poller/`. One-way dependency.
2. MCP tools (`tools.py`) contain no SQL and no HTTP — they call `service.py`
   functions and format the result. Each tool is ~5 lines.
3. Clients return typed `pydantic` objects. The rest of the code does not know
   whether data came from Magic Bus or TheRide.

### Why two processes

The poller must run continuously to build the historical dataset; the MCP
server is launched on demand by Claude clients and may exit between sessions.
Coupling them would mean either losing data when the client closes or running
the poller every time someone asks a question. The SQLite database is the seam.

## Components and repo layout

```
umich-transit-mcp/
├── pyproject.toml              # declares mcp + poller entry points
├── README.md                   # demo gif, architecture, quickstart, FAQ
├── .env.example
├── alembic.ini
├── src/umich_transit/
│   ├── core/
│   │   ├── clients/
│   │   │   ├── mbus.py         # Magic Bus / DoubleMap client
│   │   │   └── theride.py      # AAATA GTFS-RT client
│   │   ├── storage/
│   │   │   ├── db.py
│   │   │   ├── models.py
│   │   │   ├── queries.py
│   │   │   └── migrations/
│   │   ├── reliability.py      # stats engine
│   │   ├── planner.py          # trip planner
│   │   └── service.py          # orchestrates clients + queries + stats
│   ├── mcp_server/
│   │   ├── __main__.py
│   │   ├── server.py
│   │   └── tools.py
│   └── poller/
│       ├── __main__.py
│       ├── runner.py
│       └── arrival_detector.py
├── tests/
└── scripts/
    └── seed_static_data.py     # one-time routes/stops backfill
```

Entry points declared in `pyproject.toml`:

```toml
[project.scripts]
umich-transit-mcp    = "umich_transit.mcp_server.__main__:main"
umich-transit-poller = "umich_transit.poller.__main__:main"
```

## MCP tools

Six tools; the first five are the MVP. Every tool is read-only and returns a
structured object plus a `summary` string field.

| Tool | Purpose |
|---|---|
| `list_routes(agency=None)` | All routes; optional `"mbus"` / `"theride"` filter. |
| `find_stops(query, near=None, limit=5)` | Fuzzy stop search; optional `(lat, lon)` for nearest. |
| `get_arrivals(stop_id, route_id=None, limit=5)` | The headline tool. Returns `[{route, vehicle_id, predicted_at, reliability_adjusted_at, on_time_pct_at_this_hour, sample_size}]`. |
| `route_reliability(route_id, day_of_week=None, hour=None)` | Stats: on-time %, mean delay, p90 delay, sample count. |
| `plan_trip(from_, to_, leave_by=None, arrive_by=None)` | Walking + bus segments with reliability-aware arrival time. |
| `stop_reliability(stop_id, route_id=None)` *(stretch)* | Same shape as `route_reliability`, scoped to one stop. |

Tool selection is driven by docstrings; each tool gets a clear one-sentence
description and a worked example in its docstring.

## Data model

Six tables. Two static, two high-volume, one derived, one join table.

```
routes(id, agency, short_name, long_name, color, raw_json, updated_at)
stops(id, agency, name, lat, lon, raw_json, updated_at)
route_stops(route_id, stop_id, sequence)

predictions(id, route_id, stop_id, vehicle_id,
            predicted_arrival_at, captured_at)         -- HIGH VOLUME

arrivals(id, route_id, stop_id, vehicle_id,
         actual_arrival_at, detected_via)

reliability_stats(route_id, stop_id, dow, hour,
                  on_time_pct, mean_delay_s,
                  p50_delay_s, p90_delay_s,
                  sample_count, updated_at)
```

### Volume sizing

- ~10 active routes, ~30 stops each, 30s polling, ~18 service hours/day
- ~0.5-1M `predictions` rows per day; pruned after 90 days
- `reliability_stats` is ~10 × 30 × 7 × 24 ≈ 50k rows, recomputed nightly
- SQLite in WAL mode handles this comfortably

### Indexes (created in initial migration)

- `predictions(stop_id, route_id, captured_at)` — hot live query
- `arrivals(vehicle_id, actual_arrival_at)` — arrival detector lookback
- `reliability_stats(route_id, stop_id, dow, hour)` — bin lookup

### `raw_json` columns

Both `routes` and `stops` retain the raw upstream payload. If Magic Bus or
AAATA changes their schema, we reparse from the stored payload rather than
re-fetching, and we have an audit trail.

## Poller and reliability engine

Two async loops plus one nightly batch job.

### Loop 1: prediction logger (every 30s)

For each agency: fetch all upcoming ETAs for all active vehicles, bulk-insert
one row per `(vehicle, stop, predicted_arrival_at, captured_at)`. No clever
logic; we are building a time series of "what did the API say at each moment."

### Loop 2: arrival detector (every 15s)

The hard part: the API never emits arrival events. We infer them from GPS
positions using a hysteresis state machine.

```
For each vehicle:
    state = APPROACHING | AT_STOP | DEPARTED   # in-memory, per vehicle
    For each stop on its current route:
        distance = haversine(vehicle.pos, stop.pos)
        if state == APPROACHING and distance < 30m:
            record arrival(vehicle, stop, now)
            state = AT_STOP
        elif state == AT_STOP and distance > 50m:
            state = DEPARTED  # ready for next stop
```

**Hysteresis** (30m enter, 50m exit) prevents flapping at the boundary when
GPS jitters.

**Cross-check via prediction collapse:** when the Magic Bus ETA for a vehicle
at a stop hits "arriving" and then disappears, that is a secondary arrival
signal. If proximity and collapse disagree by more than 60s for the same
vehicle/stop, log a discrepancy row for offline review.

**Edge cases handled:**

- GPS jitter near the threshold → hysteresis absorbs it
- Bus skips a stop → state never enters `AT_STOP`, no false arrival
- Bus halts at a light near a stop → distance stays > 30m, no false arrival
- Process restart → state rebuilt from last 5 min of position history
- Vehicle disappears from API → `APPROACHING` state times out after 10 min

### Nightly batch: reliability stats

Once nightly, in low-traffic hours:

```
For each (route, stop, day_of_week, hour) bin:
    Pull arrivals from last 90 days in that bin
    For each arrival, find the prediction captured ~5 min before it
    delay = actual_arrival_at - predicted_arrival_at
    Compute: mean_delay, p50, p90, on_time_pct (|delay| ≤ 2 min), sample_count
    Upsert into reliability_stats
```

**5-minute lookback** for prediction matching: we want to grade "how accurate
is the prediction when a user actually checks it." Grading a 1-second-old
prediction is meaningless; grading a 5-minute-old one is what users care about.
Configurable.

**Cold-start handling:** if `sample_count < 20` for a bin, the API surfaces
predictions with `confidence: "low"` and no adjustment. Honest beats fake.

### What the live tool actually does

```python
def get_arrivals(stop_id, route_id=None):
    live = mbus_client.get_etas(stop_id, route_id)             # network
    for p in live:
        bin = (p.route_id, p.stop_id, today_dow, now_hour)
        stats = reliability_stats.get(bin)                      # O(1) index hit
        p.adjusted_arrival = p.predicted_arrival + stats.mean_delay
        p.confidence = "high" if stats.sample_count >= 50 else "low"
    return live
```

## Error handling

| Failure | Behavior |
|---|---|
| Upstream API 5xx / timeout | Poller: exponential backoff, circuit breaker after 5 fails, structured log + alert. MCP tools: serve last-known DB data with `stale: true`. |
| Schema change in upstream payload | Pydantic parse fails → row written to `parse_errors` table with raw JSON, loop continues. |
| Empty DB (cold start) | Tools return live API data with `confidence: "low"`. |
| Vehicle drops out mid-route | `APPROACHING` state times out after 10 min and is dropped. |
| Clock skew | All durations use API-provided `captured_at`; local clock used only for "now" comparisons in the detector. |
| SQLite locked | WAL mode + short retry; poller writes, MCP reads, no contention in practice. |

Logging via `structlog` (JSON lines). One info-level log per polling cycle,
warnings for backoff/circuit-breaker, errors for parse failures.

## Testing strategy

**Unit tests (the bulk of the suite, target 80%+ coverage on `core/`)**

- `core/reliability.py` — synthetic predictions/arrivals → assert computed stats
- `core/clients/` — recorded JSON fixtures → parser → typed objects (no network)
- `poller/arrival_detector.py` — synthetic GPS trail → assert exactly N arrival
  events at the right stops. Written first (TDD); this is the algorithmic core.

**Integration tests**

- In-memory SQLite, run a fake polling cycle end-to-end, assert row shape and
  relationships
- MCP server in-process, call each tool, snapshot the response shape

**Manual / smoke**

- `mcp dev` against the real Magic Bus API for the demo GIF and final check

## README plan

The README is the highest-ROI surface for recruiters and reviewers. Sections,
in order:

1. **Hero** — one-sentence pitch, animated GIF of Claude using a tool, badges
2. **The problem** — two sentences with a real example
3. **The approach** — ASCII architecture diagram
4. **Quickstart** — four copy-pasteable commands + MCP config snippet
5. **Tool reference** — table with one-line descriptions and example outputs
6. **How reliability scoring works** — ~200 words plus a chart generated from
   real collected data (committed as PNG)
7. **Roadmap** — bullets: FastAPI HTTP layer, Next.js dashboard, TheRide
   integration, crowdsourced arrivals
8. **Tech stack & decisions** — FAQ format: "Why SQLite?" "Why a separate
   poller?" "Why not just GTFS?" — 2-3 sentences each

## Repo polish

- GitHub Actions: `ruff` lint, `mypy` typecheck, `pytest` test, coverage upload
- Pre-commit hooks (ruff)
- `CHANGELOG.md` updated with each release
- `screenshots/` directory: demo GIF + reliability chart from real data
- MIT license
- GitHub topic tags: `mcp`, `model-context-protocol`,
  `university-of-michigan`, `transit`, `python`

## Deployment options (documented in README)

1. **Local laptop** — works for getting started, but the poller dataset has
   gaps when the laptop sleeps
2. **Free-tier VPS** (Oracle Cloud / Fly.io) — recommended; ships with sample
   systemd unit + Dockerfile
3. **Raspberry Pi at home** — fun option with a short setup section

A continuously-running deployment is itself part of the story: *"the poller
has been running for 6 months and collected 18M data points."*

## Open questions

- Magic Bus API key registration flow — needs an account; document the steps in
  README during implementation.
  - **RESOLVED (2026-06-02):** Live probing showed Magic Bus now runs the
    **Clever Devices BusTime API v3** (`/bustime/api/v3`), not DoubleMap. It
    requires `?key=&format=json` and wraps responses in `{"bustime-response":{}}`.
    A free key requires developer-account registration. The client targets
    BusTime; timestamps are `America/Detroit` and converted to UTC on write.
- Whether to also ingest AAATA GTFS-static schedule data in MVP, or only their
  real-time feed. Leaning real-time only for MVP; static can be backfilled.
- Trip planner v1 supports only same-route trips (no transfers). Transfers
  pushed to v2.

## Out of scope (explicit non-goals to defer)

- HTTP API layer
- Next.js dashboard
- User accounts / saved preferences
- Push notifications
- Multi-modal routing (walk/bike/drive segments)
- Service alert ingestion (different upstream endpoint)
- Dining, courses, library, events — separate projects

## Sequencing for the implementation plan

The implementation plan (next step) will likely sequence work roughly as:

1. Project scaffold (`pyproject.toml`, `uv`, package skeleton, CI config)
2. Storage layer (models, migrations, queries) — TDD against a unit suite
3. Magic Bus client (typed, with fixtures)
4. Poller: prediction logger loop
5. Arrival detector (TDD with synthetic GPS trails) — the algorithmic core
6. Reliability nightly job
7. MCP server skeleton + first tool (`list_routes`)
8. Remaining MCP tools
9. Trip planner (same-route v1)
10. README polish, demo GIF, deployment docs
11. Stretch: TheRide GTFS-RT client, `stop_reliability` tool
