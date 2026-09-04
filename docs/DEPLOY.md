# Deploying Honest ETA

The public web application and the continuous collector have different runtime
needs:

```text
Vercel FastAPI web function ---> PostgreSQL <--- always-on poller container
```

Vercel serves the recruiter-facing site and request-driven API. It must not run
the polling loops. The poller needs an always-on container or service because it
collects predictions every two minutes and vehicle positions every 30 seconds.

## Phase 1: Vercel demo deployment

Demo mode is database-free and requires no BusTime secret. Import the GitHub
repository into Vercel or deploy an authenticated checkout with the Vercel CLI.
The checked-in `vercel.json` sets `TRANSIT_APP_MODE=demo`, routes requests to
the file-based FastAPI entry point, and bundles both the static site and
versioned fixtures. The project requires Python 3.12, the oldest Python runtime
currently supported by Vercel.

After deployment, verify the generated URL:

```bash
uv run python scripts/smoke_public_demo.py --base-url https://YOUR-PROJECT.vercel.app
```

The last deployed build is
[honest-eta-theta.vercel.app](https://honest-eta-theta.vercel.app). Treat it as
unverified after application changes until the exact preview and production
deployments pass the automated smoke plus desktop/mobile browser checks.

Every check must pass before sharing the link. Preview and production pages must
display the `Demo data` banner; illustrative accuracy numbers are not real-world
performance claims.

## Phase 2: live PostgreSQL deployment

Create a managed PostgreSQL database only after the demo deployment is stable.
Configure these environment variables for the Vercel production environment
and the poller host:

```text
TRANSIT_APP_MODE=live
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
MBUS_API_KEY=your-key
```

Do not expose these values in client-side JavaScript, screenshots, logs, or the
repository. Run Alembic migrations against the destination before starting the
poller. The migration command below does that automatically.

To preserve an existing SQLite history, stop the SQLite poller first so its WAL
is consistent, then run:

```bash
uv run python scripts/migrate_database.py \
  --source-url sqlite:///./data/transit.db \
  --destination-url "$DATABASE_URL"
```

The command refuses a non-empty destination by default, prints verified row
counts, never deletes the source, and redacts database passwords. Use
`--replace` only when intentionally replacing every application table in the
destination.

Rollback is configuration-only: set the web deployment back to demo mode and
restart the previous SQLite poller. Keep the source SQLite file until the live
deployment has collected and served data successfully.

## Phase 3: custom domain

Attach the chosen domain only after the generated `*.vercel.app` production URL
passes the smoke check. Domain purchase and DNS changes are deliberately not
part of the automated deployment workflow.

## Deploying the poller for 24/7 collection

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

## Option C — macOS (launchd, laptop stopgap)

Not truly 24/7 (a laptop sleeps), but useful while you set up a server: this
runs the poller automatically whenever your Mac is on — auto-start at login,
auto-restart on crash, and it keeps the Mac awake while running. Run from the
repo directory; the heredoc fills in your `uv` path and project dir for you:

```bash
cat > ~/Library/LaunchAgents/com.umich-transit.poller.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.umich-transit.poller</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-is</string>
    <string>$(command -v uv)</string><string>run</string><string>umich-transit-poller</string>
  </array>
  <key>WorkingDirectory</key><string>$(pwd)</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>$(pwd)/poller.log</string>
  <key>StandardErrorPath</key><string>$(pwd)/poller.log</string>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
EOF
launchctl load -w ~/Library/LaunchAgents/com.umich-transit.poller.plist
```

Manage it:

```bash
launchctl list | grep umich-transit     # a PID number = running
tail -f poller.log                       # watch it
launchctl unload -w ~/Library/LaunchAgents/com.umich-transit.poller.plist   # stop + disable
launchctl load   -w ~/Library/LaunchAgents/com.umich-transit.poller.plist   # start again
```

(A pre-filled template also lives at `deploy/com.umich-transit.poller.plist`.)

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

2. **Use PostgreSQL for the live app** — point the server-side poller, Vercel
   application, and optional local MCP server at one managed PostgreSQL
   `DATABASE_URL`. Follow Phase 2 above to migrate existing SQLite history.

## Notes

- `.env` is never baked into the image and is git-ignored — your key stays on
  the host only.
- The DB persists across `docker compose up --build` rebuilds (named volume).
- Reliability stats fill in over days; `get_arrivals` reports
  `confidence: high` once a route/stop/hour bin reaches ≥ 50 samples.
