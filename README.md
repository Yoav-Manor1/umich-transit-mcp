# TrueBlue Transit

**Better estimates for when your U-M bus will actually arrive.**

TrueBlue Transit compares published bus times with how buses have arrived in
the past. When there is enough evidence, it gives riders a more useful arrival
estimate, explains the change, and shows how confident it is.

The project includes a mobile-friendly dashboard and an MCP server backed by
the same reliability engine.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-dashboard-009688)
![MCP](https://img.shields.io/badge/MCP-5_tools-6C47FF)
![License](https://img.shields.io/badge/license-MIT-green)

## Try it in 30 seconds

No API key or live bus service is needed for the sample demo.

```bash
uv sync --all-extras
uv run umich-transit-demo
```

The dashboard opens at [http://127.0.0.1:8000](http://127.0.0.1:8000).
Search for **Central Campus Transit Center**, **Pierpont Commons**, or
**Bursley Hall**.

The demo uses sample history and generates fresh upcoming arrivals on every
request. It is stored separately from real observations and is marked
**Sample times** in the header.

## What you can do

### Know when to leave

Search for a campus stop, choose how many minutes it takes to walk there, and
see when you should leave. Each arrival shows:

- The published arrival time
- A history-adjusted estimate when enough evidence exists
- High, medium, or low confidence
- The number of past arrivals supporting the estimate
- A plain-language explanation of why the time changed
- A warning when the real feed has stopped updating

Favorite stops and walking times stay in the browser.

### Check whether the estimates are really better

The **Accuracy Proof** view tests the approach instead of assuming it works.
The oldest 80% of arrivals builds the correction; the newest 20% remains
unseen until evaluation.

It compares published and adjusted results using:

- Mean and median absolute error
- Remaining early/late bias
- Percentage of arrivals within two minutes
- Overall and route-level results

The dashboard reports **improved**, **tied**, or **worsened**. It does not hide
a negative result.

## How it works

1. **Record published estimates.** The poller saves what the bus system
   predicted and when the prediction was made.
2. **Detect actual arrivals.** Vehicle GPS observations identify when a bus
   enters a stop area. Hysteresis prevents a bus waiting at a stop from being
   counted repeatedly.
3. **Compare the same rider decision point.** Each arrival is matched to the
   eligible prediction closest to five minutes beforehand, within a
   ±90-second window. A prediction cannot be reused.
4. **Learn recurring differences.** The correction is the median historical
   early/late error for that route, stop, weekday, and hour. Broader route
   history is used only when the exact group is too small.
5. **Adjust carefully.** High confidence requires 30 exact examples. Medium
   confidence requires 20 examples from a broader group. With less evidence,
   the published time is left unchanged.

Time groups use `America/Detroit`. Adjustments are limited to ±10 minutes, and
all matching and model versions are stored with the generated analytics.

## Dashboard and MCP

Both interfaces call the same `TransitService`, so conversational answers and
the dashboard use identical arrival and accuracy logic.

| MCP tool | What it answers |
|---|---|
| `list_routes` | Which routes are available? |
| `find_stops` | Which stops match a name or nearby location? |
| `get_arrivals` | When is the next bus, was its time adjusted, and why? |
| `route_reliability` | How often is this route on time? |
| `prediction_accuracy` | Did adjusted times beat published times on future arrivals? |

To try the sample dataset through MCP:

```json
{
  "mcpServers": {
    "trueblue-transit": {
      "command": "uv",
      "args": ["run", "umich-transit-demo-mcp"],
      "cwd": "/absolute/path/to/umich-transit-mcp"
    }
  }
}
```

Questions to try:

- “When is the next Commuter North bus at CCTC?”
- “Why was that arrival time changed?”
- “How fresh is the bus information?”
- “Are the adjusted estimates more accurate overall?”
- “Does the correction help route CN?”

## Architecture

```text
Published estimates ──┐
                     ├──> SQLite observations ──> matched outcomes
Vehicle locations ───┘                               │
                                                     ├──> reliability profiles
                                                     └──> accuracy evaluation
                                                                  │
                                     ┌────────────────────────────┴────────┐
                                     ▼                                     ▼
                              FastAPI dashboard                       MCP server
```

- `core/` owns clients, storage, matching, reliability profiles, evaluation,
  and the shared service API.
- `poller/` records predictions and positions, detects arrivals, and rebuilds
  derived analytics.
- `web/` presents the responsive dashboard without containing reliability
  calculations or SQL.
- `mcp_server/` registers five focused, read-only tools over the shared service.

Raw predictions and arrivals are the source of truth. Outcomes, profiles, and
evaluation reports are versioned, derived data that can be rebuilt.

## Engineering highlights

- Deterministic, one-command demo with an isolated SQLite database
- Responsive dashboard verified at desktop and mobile breakpoints
- Evidence-based fallback hierarchy instead of an opaque model
- Chronological evaluation that prevents training/test leakage
- Explicit low-confidence and insufficient-evidence states
- Last-good-board behavior during upstream failures
- Five-minute stale-feed detection for real observations
- Alembic migrations for outcomes, profiles, and evaluation reports
- Strict MyPy, Ruff, integration tests, and a black-box showcase smoke check

## Use real Magic Bus data

Register for a BusTime API key through the Magic Bus developer portal, then:

```bash
cp .env.example .env
# Set MBUS_API_KEY in .env

uv sync --all-extras
uv run alembic upgrade head
uv run python scripts/seed_static_data.py
uv run umich-transit-poller
```

In another terminal:

```bash
uv run umich-transit-web
```

The poller begins building real history immediately. Adjustments remain off
until a group reaches its evidence threshold. Analytics refresh when the
poller starts and every 24 hours.

For deployment options already included in the repository, see
[docs/DEPLOY.md](docs/DEPLOY.md).

## Verify the project

```bash
uv run python scripts/smoke_showcase.py
uv run pytest --cov=umich_transit --cov-report=term-missing
uv run ruff check .
uv run mypy src
```

The smoke check creates an isolated demo database, exercises the dashboard
health, search, accuracy, and static assets, and verifies the MCP tool surface.

## Current limitations

- GPS polling can miss a bus that passes a stop entirely between observations.
- Proximity detection is a careful estimate, not official arrival telemetry.
- Detector state is kept in memory and resets with the poller.
- Sparse routes and time groups remain unadjusted.
- BusTime timestamps are ambiguous during the repeated fall-back DST hour.
- Transfers, full trip planning, TheRide integration, accounts, Postgres, and
  public hosting are intentionally outside the current local showcase.

## Two-minute walkthrough

1. Run `uv run umich-transit-demo`.
2. Search for CCTC and compare the published and adjusted arrival.
3. Change the walking time and show the “leave in” guidance.
4. Open **Accuracy Proof** and explain the 80/20 past-versus-future test.
5. Ask the same arrival or accuracy question through MCP.
6. Run the smoke check to finish with automated evidence.

## License

MIT — see [LICENSE](LICENSE).
