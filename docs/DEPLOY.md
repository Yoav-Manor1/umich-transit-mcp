# Deploying the poller for 24/7 collection

The poller must run continuously to build the reliability dataset. A laptop
isn't ideal (it sleeps), so run it on a small always-on Linux box. This guide
uses Docker (recommended) or systemd, on any Ubuntu 22.04+ host.

## 0. Get a host

Any always-on Linux VM works. Free options:

- **Oracle Cloud "Always Free"** (recommended) — a genuinely free-forever VM
  (an Ampere ARM or AMD micro instance). Sign up at cloud.oracle.com, create an
  **Always Free** Ubuntu compute instance, and save the SSH key.
- **Google Cloud `e2-micro` free tier**, **Fly.io**, or any ~$4/mo VPS
  (Hetzner, DigitalOcean, Linode) if you'd rather skip the free-tier friction.

The workload is tiny (a few API calls every 15–30s), so the smallest instance
is plenty.

SSH in:

```bash
ssh ubuntu@<your-server-ip>
```

## Option A — Docker (recommended)

```bash
# 1. Install Docker + the compose plugin
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker   # run docker without sudo

# 2. Clone the repo
git clone https://github.com/Yoav-Manor1/umich-transit-mcp.git
cd umich-transit-mcp

# 3. Configure your API key
cp .env.example .env
nano .env            # set MBUS_API_KEY=<your key>, save

# 4. Build and start (detached, auto-restarting)
docker compose up -d --build

# 5. Watch it work
docker compose logs -f
```

You should see `prediction_loop.tick` with `inserted > 0` and
`arrival_loop.tick` with `vehicles > 0` during service hours.

It now survives crashes and host reboots (`restart: unless-stopped`, and Docker
starts on boot). **Done — it's collecting 24/7.**

Useful commands:

```bash
docker compose ps                  # status
docker compose logs --tail=50      # recent logs
docker compose pull && docker compose up -d --build   # update after a git pull
docker compose down                # stop (data persists in the volume)
```

## Option B — systemd (no Docker)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo ln -sf ~/.local/bin/uv /usr/local/bin/uv

# Clone to /opt and configure
sudo git clone https://github.com/Yoav-Manor1/umich-transit-mcp.git /opt/umich-transit-mcp
cd /opt/umich-transit-mcp
sudo cp .env.example .env && sudo nano .env     # set MBUS_API_KEY
sudo uv sync --frozen
sudo uv run python scripts/seed_static_data.py  # one-time seed

# Install + start the service
sudo cp deploy/umich-transit-poller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now umich-transit-poller
journalctl -u umich-transit-poller -f           # watch logs
```

## Using the collected data with Claude (locally)

The poller now writes the SQLite DB on the **server**, while the MCP server runs
on your **laptop** (launched by Claude Desktop). Two ways to bridge that:

1. **Pull a snapshot down** (simplest). The poller is the only writer, so a
   read-only copy is safe:
   ```bash
   # Docker host:
   docker compose cp poller:/app/data/transit.db ./data/transit.db
   # then scp it to your laptop, or run directly on the server.
   # systemd host:
   scp ubuntu@<server-ip>:/opt/umich-transit-mcp/data/transit.db ./data/transit.db
   ```
   Drop it at `data/transit.db` locally and the MCP server reads it. Re-pull
   whenever you want fresh reliability stats.

2. **Move to Postgres** (the "real app" path, on the roadmap) — point both the
   server-side poller and your local MCP server at one managed Postgres via
   `DATABASE_URL`. The storage layer is already SQLAlchemy, so this is a
   connection-string change plus running migrations against Postgres.

## Notes

- `.env` is never baked into the image and is git-ignored — your key stays on
  the host only.
- The DB persists across `docker compose up --build` rebuilds (named volume).
- Reliability stats fill in over days; `get_arrivals` reports
  `confidence: high` once a route/stop/hour bin reaches ≥ 50 samples.
