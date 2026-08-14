# U-Mich Transit Intelligence

Magic Bus tells you when a bus *should* arrive. This project measures when it
actually arrives, learns recurring prediction bias, and only adjusts an ETA when
the historical evidence is strong enough.

> Magic Bus said four minutes. Historical evidence suggested nine. The bus
> arrived in ten.

The same transparent reliability engine powers a polished local dashboard and
five read-only MCP tools. A chronological holdout report shows whether the
adjustment really helps; negative results are reported rather than hidden.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

## Try the complete showcase

No API key or live bus service is required:

```bash
uv sync --all-extras
uv run umich-transit-demo
```

This creates a separate `data/demo-transit.db`, opens
`http://127.0.0.1:8000`, and clearly labels the synthetic-but-realistic demo
data. Search for **Central Campus Transit Center**, **Pierpont Commons**, or
**Bursley Hall**, then switch to **Accuracy proof** to see the held-out
evaluation.

For the same deterministic evidence through MCP, configure your client to run
`uv run umich-transit-demo-mcp`. It uses its own
`data/demo-transit-mcp.db`, so the conversational and dashboard demos remain
isolated from live observations.

The demo timeline is shifted relative to startup, so arrivals stay upcoming
while historical intervals and expected metrics remain deterministic. Demo data
never touches the live database.

## What makes the result credible

1. **Capture predictions.** The poller batches Magic Bus predictions every 120
   seconds and retains their capture time.
2. **Infer arrivals.** Vehicle GPS is sampled every 30 seconds. Entering within
   30 metres of a route stop emits an arrival; the vehicle must leave 50 metres
   before it can trigger again.
3. **Grade one rider decision point.** Each arrival is matched to the eligible
   prediction closest to five minutes beforehand, within a ±90-second tolerance.
   Predictions cannot be reused.
4. **Learn explainable bias.** The correction is a clamped median signed error.
   It tries route + stop + weekday + hour first, then two broader route-level
   fallbacks. High confidence requires 30 exact samples; medium requires 20
   fallback samples; low confidence leaves the published ETA unchanged.
5. **Test on the future.** The oldest 80% of outcomes trains frozen profiles;
   the newest 20% is held out. Published and adjusted mean/median absolute
   error, bias, and within-two-minutes rate are reported overall and for routes
   with at least 20 held-out arrivals.

All time buckets use `America/Detroit`. The matching rule, model, thresholds,
and report versions are visible in stored derived artifacts and API responses.

## Product surfaces

### Dashboard

```bash
uv run umich-transit-web
```

The mobile-friendly page has two views:

- **Live board:** stop search, browser-local favorites, per-stop walk time,
  when-to-leave guidance, published versus adjusted ETA, confidence,
  explanation, and stale-feed status.
- **Accuracy proof:** overall and route-level held-out results plus the visible
  80/20 methodology.

If Magic Bus fails, the browser keeps the last good board and shows a retry
notice instead of replacing useful information with an empty state.

### MCP

| Tool | Purpose |
|---|---|
| `list_routes` | List seeded routes, optionally by agency |
| `find_stops` | Search stops by name or proximity |
| `get_arrivals` | Live published and evidence-adjusted ETAs with explanations |
| `route_reliability` | Historical on-time rate and delay summary |
| `prediction_accuracy` | Held-out published-versus-adjusted accuracy, optionally by route |

The earlier approximate trip planner is intentionally not registered: it did
not validate direction or calculate travel time, so exposing it would overstate
what the project can do.

Claude Desktop configuration:

```json
{
  "mcpServers": {
    "umich-transit": {
      "command": "uv",
      "args": ["run", "umich-transit-demo-mcp"],
      "cwd": "/absolute/path/to/umich-transit-mcp"
    }
  }
}
```

Replace `umich-transit-demo-mcp` with `umich-transit-mcp` when you want the
configured live database and Magic Bus API.

Good questions to try:

- “When is the next Commuter North bus at CCTC, and why did you adjust it?”
- “How fresh is that prediction?”
- “Do adjusted predictions actually beat Magic Bus overall?”
- “Does the correction help on route CN specifically?”

## Architecture

```text
BusTime predictions ──┐
                     ├─> SQLite raw observations ─> matched outcomes
Vehicle GPS ─────────┘                              │
                                                    ├─> reliability profiles
                                                    └─> holdout evaluation
                                                              │
                                ┌─────────────────────────────┴──────────┐
                                ▼                                        ▼
                         FastAPI dashboard                          MCP server
```

- `core/` owns normalization, storage, matching, profiles, evaluation, and the
  shared `TransitService` API.
- `poller/` owns continuous collection, arrival detection, and analytics
  refreshes.
- `web/` and `mcp_server/` are thin presentation layers with no reliability
  math or SQL.
- SQLite WAL mode is the only supported database for this local milestone.

Raw predictions and arrivals are the source of truth. Outcomes, profiles, and
evaluation reports are derived and rebuildable.

## Collect live data

Register for a free BusTime API key through the Magic Bus developer portal,
then:

```bash
cp .env.example .env
# Set MBUS_API_KEY in .env

uv sync --all-extras
uv run alembic upgrade head
uv run python scripts/seed_static_data.py
uv run umich-transit-poller
```

Run `uv run umich-transit-web` in another terminal. Analytics refresh when the
poller starts and every 24 hours. Confidence and evaluation coverage grow as
real observations accumulate.

For always-on collection, the repository includes Docker, systemd, and launchd
options in [docs/DEPLOY.md](docs/DEPLOY.md).

## Known limitations

- GPS polling can miss a bus that passes a stop entirely between samples.
- The proximity detector is intentionally conservative but is not ground-truth
  schedule telemetry.
- Detector hysteresis state is in memory and resets with the poller.
- BusTime timestamps are ambiguous during the repeated DST fall-back hour; the
  earlier offset is used.
- Sparse routes or time bins remain unadjusted rather than borrowing a
  cross-route global correction.
- Transfers, full trip planning, TheRide integration, accounts, Postgres, and
  public hosting are deferred.

## Verification

```bash
uv run python scripts/smoke_showcase.py
uv run pytest --cov=umich_transit --cov-report=term-missing
uv run ruff check .
uv run mypy src
```

The smoke command builds an isolated demo database, exercises web health,
search, accuracy, and static assets, and verifies the public MCP tool surface.

## Two-minute demo flow

1. Run `uv run umich-transit-demo`.
2. Search for CCTC and compare the published and adjusted arrival guidance.
3. Open **Accuracy proof** and explain the chronological 80/20 split.
4. Ask the equivalent arrival and accuracy questions through MCP.
5. Show that both surfaces use `TransitService`, then run the smoke command.

## License

MIT — see [LICENSE](LICENSE).
