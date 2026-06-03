#!/usr/bin/env sh
# Container entrypoint: bring the schema up to date, seed static data
# (idempotent), then run the poller in the foreground as PID 1's child.
set -e

mkdir -p data

echo "[entrypoint] applying migrations..."
uv run alembic upgrade head

echo "[entrypoint] seeding static data (routes/stops/route_stops)..."
uv run python scripts/seed_static_data.py || \
  echo "[entrypoint] seed failed (bad key or no network?) - continuing with existing data"

echo "[entrypoint] starting poller..."
exec uv run umich-transit-poller
