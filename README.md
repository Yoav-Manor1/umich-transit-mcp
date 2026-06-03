# U-Mich Transit MCP Server

An MCP server that gives Claude *honest* answers about University of Michigan
buses. It doesn't just relay the Magic Bus arrival predictions — it logs them,
infers actual arrivals from live GPS, and learns the gap between the two.

> "Magic Bus says 4 minutes. The bus shows up in 12.
> This server learns from that gap and tells you the difference."

<!-- TODO: record a ~20s GIF of Claude using get_arrivals / plan_trip, save it as
     screenshots/demo.gif, and uncomment the next line:
![demo](screenshots/demo.gif)
-->

![Python](https://img.shields.io/badge/python-3.11+-blue)
![Tests](https://img.shields.io/badge/tests-73%20passing-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

## What it does

Five read-only MCP tools:

| Tool | What it answers |
|------|-----------------|
| `list_routes` | What routes exist (filter by agency) |
| `find_stops` | Find a stop by name, or the nearest stops to a coordinate |
| `get_arrivals` | **The headline.** Upcoming arrivals at a stop with both the *published* ETA and a *reliability-adjusted* ETA, plus a confidence level |
| `route_reliability` | On-time %, mean delay, and sample count for a route |
| `plan_trip` | Soonest single-route trip between two stops, ranked by reliability-adjusted arrival |

## The problem

Real-time transit predictions are optimistic. The published ETA assumes nominal
conditions; the bus that's actually coming is subject to traffic, weather, and
dwell time. Riders learn the patterns by hard experience ("Commuter North always runs late
on weekday evenings"). This server encodes that learning so an assistant can
hand it to you directly.

## Architecture

Two long-running processes share a database; a core library holds all the logic
so the same code can later back an HTTP API and a web dashboard.

```
┌────────────────┐     ┌────────────────┐     ┌─────────────────────┐
│  MCP Server    │     │  HTTP API      │     │  Next.js dashboard  │
│  (5 tools)     │     │  (planned)     │     │  (planned)          │
└───────┬────────┘     └───────┬────────┘     └──────────┬──────────┘
        │                      │                         │
        ▼                      ▼                         ▼
┌──────────────────────────────────────────┐
│  umich_transit.core                      │
│  clients · storage · reliability ·       │
│  planner · service                       │
└───────────────────┬──────────────────────┘
                    ▼
┌──────────────────────────────────────────┐
│  SQLite (WAL)  →  Postgres for the app    │
└───────────────────▲──────────────────────┘
                    │
┌───────────────────┴──────────────────────┐
│  Background poller                        │
│   • prediction logger   (every 30s)       │
│   • arrival detector    (every 15s)       │
│   • nightly stats recompute               │
└──────────────────────────────────────────┘
```

The MCP server is stateless and launched on demand by a Claude client. The
poller runs continuously to build the historical dataset. They never call each
other — the SQLite database is the only seam.

## How reliability scoring works

1. **Log predictions.** Every 30s the poller pulls arrival predictions from the
   BusTime API and stores `(route, stop, vehicle, predicted_time, captured_at)`.
2. **Detect real arrivals.** Every 15s it reads live vehicle GPS and infers
   arrivals with a hysteresis state machine: a bus entering 30m of a stop is an
   arrival; it must leave 50m before it can re-trigger. Hysteresis absorbs GPS
   jitter so a bus idling near a stop isn't counted twice.
3. **Grade the predictions.** Nightly, each detected arrival is matched to the
   prediction made ~5 minutes earlier (when a rider would actually have checked),
   and the signed delay is bucketed by route, stop, **local** day-of-week, and
   hour.
4. **Serve honest ETAs.** `get_arrivals` adds the historical mean delay for the
   current bin to the live prediction, and reports `confidence: high` once a bin
   has ≥ 50 samples (otherwise `low`, with no adjustment).

## Quickstart

You need a free **BusTime API key** for Magic Bus. Register a developer account
via the Magic Bus developer portal (linked from `mbus.ltp.umich.edu`) and copy
your key.

```bash
git clone <your-repo-url> umich-transit-mcp
cd umich-transit-mcp
uv sync --all-extras

cp .env.example .env
# edit .env and set MBUS_API_KEY=<your key>

uv run alembic upgrade head          # create the database schema
uv run python scripts/seed_static_data.py   # load routes, stops, route_stops
uv run python -m umich_transit.poller        # run continuously (own terminal)
```

Connect it to Claude Desktop (`claude_desktop_config.json`):

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

Then ask Claude things like *"When's the next Commuter North bus at the Central
Campus Transit Center, and is it usually on time right now?"* or *"Plan a trip
from Pierpont Commons to the Central Campus Transit Center."*

## Known limitations

- **Polling-based arrival detection.** If a bus passes a stop entirely between
  two GPS polls (never observed within 30m), that arrival isn't recorded. Higher
  poll frequency narrows the gap; it can't close it entirely.
- **DST fall-back hour.** BusTime emits naive local timestamps. During the one
  ambiguous hour when clocks fall back in November, a timestamp can't be
  disambiguated from the string alone; it resolves to the earlier offset.
- **Trip planner v1 is single-route.** No transfers yet (see roadmap).
- **Detector state is in-memory.** It rebuilds after a poller restart; a handful
  of arrivals around a restart may be missed.

## FAQ

**Why SQLite instead of Postgres?**
Zero ops, ships with Python, and handles the write volume comfortably in WAL
mode. The storage layer is SQLAlchemy, so moving to Postgres for a multi-user
deployment is a connection-string change.

**Why a separate poller process?**
The dataset only exists if something polls continuously. The MCP server is
launched on demand and exits between sessions, so coupling them would either
lose data or re-poll on every question.

**Why the BusTime API and not a GTFS feed?**
Magic Bus runs the Clever Devices BusTime API, which exposes live predictions
and vehicle positions directly. Ann Arbor's city buses (TheRide) publish
GTFS-Realtime — that's on the roadmap.

**Why bin reliability by local time?**
Riders think in local time ("Thursday at 5pm"). Binning by UTC would smear the
evening rush across two local hours and misattribute late-night trips to the
wrong day.

## Roadmap

- TheRide (AAATA) GTFS-Realtime integration for Ann Arbor city buses
- `stop_reliability` tool (per-stop detail)
- Batch `get_arrivals` (BusTime accepts up to 10 stops per call)
- 90-day prediction pruning job (+ a `captured_at` index)
- FastAPI HTTP layer over the same `core/`
- Next.js dashboard with route-reliability heatmaps
- Crowdsourced arrival confirmations

## Development

```bash
uv run pytest --cov=umich_transit --cov-report=term-missing
uv run ruff check .
uv run mypy src
```

## License

MIT — see [LICENSE](LICENSE).
