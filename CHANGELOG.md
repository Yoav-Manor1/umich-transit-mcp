# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
- Clever Devices BusTime API v3 client returning agency-agnostic typed records.
- SQLite storage layer (SQLAlchemy 2.0 + Alembic), 7 tables with tuned indexes.
- Background poller: prediction logger, hysteresis-based arrival detector, and a
  nightly reliability-stats recompute job.
- Reliability engine: signed-delay binning by route/stop/local-dow/hour with
  on-time %, mean, p50, and p90.
- Service layer shared by the MCP server and a future HTTP API.
- MCP server exposing five read-only tools: `list_routes`, `find_stops`,
  `get_arrivals`, `route_reliability`, `plan_trip`.
- Same-route trip planner (v1, no transfers).
- One-time static-data seeding script (routes, stops, route_stops).
