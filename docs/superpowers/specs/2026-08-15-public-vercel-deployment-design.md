# U-Mich Transit Public Vercel Deployment - Design

**Date:** 2026-08-15
**Status:** Draft for review
**Author:** Yoav Manor
**Depends on:** `2026-08-14-showcase-finish-design.md`

## Purpose

Publish the recruiter-facing U-Mich Transit showcase at a stable Vercel URL,
then attach a custom domain after the public experience is proven. The public
site must remain understandable and useful when buses are not running, the
upstream BusTime API is unavailable, or production history is still sparse.

The deployment must not weaken the project's central claim. Live predictions,
historical corrections, and accuracy results must clearly identify their data
source, freshness, and evidence level.

## Scope

This milestone adds:

- A Vercel-compatible FastAPI entry point for the existing web application
- A deterministic public demo mode that does not require secrets or a database
- Environment-driven selection between demo and live production data
- PostgreSQL support for durable production data shared by the web application
  and the continuous poller
- A safe, documented SQLite-to-PostgreSQL migration path for collected history
- Deployment health checks, configuration validation, and recruiter-safe error
  states
- A Vercel deployment guide and production smoke check

This milestone does not add:

- Domain purchase or DNS changes
- User accounts or authentication
- A hosted remote MCP transport
- Additional transit agencies
- Paid infrastructure that the owner has not explicitly approved

The existing local stdio MCP server remains part of the repository and uses the
same core service layer. A hosted MCP endpoint can be a later milestone after
the public dashboard is stable.

## Deployment architecture

```text
Recruiter browser
       |
       v
Vercel CDN + FastAPI function
       |
       +---- demo mode ----> versioned deterministic fixtures
       |
       +---- live mode ----> managed PostgreSQL
                                  ^
                                  |
                         containerized poller
                         on an always-on host
                                  |
                                  v
                         BusTime predictions + GPS
```

Vercel owns only request-driven presentation and API traffic. It does not run
the continuous prediction and vehicle polling loops. The existing poller
remains a long-running container on an always-on host and writes to the same
PostgreSQL database read by the Vercel application.

SQLite remains the default for local development and deterministic demos.
Production live mode requires PostgreSQL because Vercel function filesystems
are ephemeral and cannot provide shared durable SQLite storage.

## Rollout strategy

### Phase 1: public deterministic preview

Deploy the completed showcase in explicit demo mode to a generated
`*.vercel.app` URL. This deployment requires no BusTime key and no production
database. It proves the build, routing, mobile layout, copy, and recruiter flow
before external infrastructure is connected.

The phase-one deployment uses illustrative arrivals and accuracy results. The
operational documentation identifies them as fixture-backed rather than
real-world performance metrics.

For this public milestone, the demo service reads the versioned showcase
fixtures directly in memory. This supersedes the SQLite-seeding mechanism in
the earlier showcase design for the web demo path; SQLite remains available for
local live-data development and the stdio MCP workflow. Direct fixture loading
keeps the public demo deterministic and avoids pretending an ephemeral Vercel
file is durable storage.

### Phase 2: live production data

Provision a managed PostgreSQL database, run Alembic migrations, migrate any
history worth preserving from the existing SQLite database, and point the
always-on poller and Vercel application at the shared `DATABASE_URL`.

Live mode continues to offer a visible `View demo` path. If live data is stale
or unavailable, the application reports the state clearly; it does not silently
substitute demo data into a live view.

### Phase 3: custom domain

After the Vercel deployment has passed production smoke checks, attach the
chosen domain. `honesteta.com` is the current preferred name, but purchase and
DNS changes remain a separate user-authorized action.

## Runtime configuration

The application uses one explicit mode variable:

- `TRANSIT_APP_MODE=demo` loads only versioned demo fixtures and requires no
  network or database secrets.
- `TRANSIT_APP_MODE=live` requires `DATABASE_URL` and `MBUS_API_KEY`; startup
  fails with an actionable configuration error if either is missing.
- Any other value is rejected. There is no silent default in a deployed Vercel
  environment.

Local development keeps the existing SQLite defaults when
`TRANSIT_APP_MODE` is unset. Secrets are read only from environment variables,
never written to the client bundle or logged.

The Vercel entry point exports one `FastAPI` instance and delegates application
construction to the existing web package. Static assets remain cacheable and
all API responses containing live data use headers that prevent stale CDN
caching.

## Database portability

The SQLAlchemy models and ordinary queries remain shared between SQLite and
PostgreSQL. Dialect-specific upsert behavior is isolated behind a storage helper
with SQLite and PostgreSQL implementations. Core reliability and evaluation
logic remains database-agnostic.

The migration command accepts explicit source and destination URLs, validates
that the destination schema is current, copies tables in dependency order, and
reports source and destination row counts. It refuses to overwrite a
non-empty destination unless an explicit replace option is supplied. The
command never deletes the source SQLite database.

Because the local collector can write through SQLite WAL, the deployment guide
requires stopping the poller or taking a consistent SQLite backup before data
migration.

## Public experience

The public landing state must answer three questions without requiring clicks:

1. What problem does this solve?
2. What is the system doing that the published ETA does not?
3. Is the viewer seeing live evidence or deterministic demo data?

The header includes links to the GitHub repository and methodology. The live
board and accuracy view use the behavior defined in the showcase design. Error,
empty-service, insufficient-evidence, demo, and stale states remain visually
distinct.

No setup instructions, API key prompts, or database errors are exposed to a
public visitor. Operational detail belongs in server logs and deployment docs.

## Health and observability

- `/api/health` reports process health and application mode without querying
  external services.
- `/api/ready` verifies the configured data source and returns a non-success
  response when live dependencies are unavailable.
- Structured logs include request path, duration, application mode, upstream
  status, and data freshness, but never secrets or full upstream payloads.
- Vercel preview deployments run in demo mode unless live environment variables
  are deliberately configured for that environment.

## Testing

### Unit tests

- Runtime mode parsing and invalid configuration
- Demo-mode service construction without secrets or database access
- Dialect-neutral reliability-stat upsert behavior
- Migration refusal for a non-empty destination
- Migration row-count validation

### Integration tests

- Vercel entry point imports and exports a FastAPI application
- Demo-mode health, readiness, stops, arrivals, accuracy, and static assets
- Live-mode startup against PostgreSQL-compatible test configuration
- SQLite remains supported for the local MCP server, demo command, and tests
- Public responses never expose the BusTime key or database URL

### Deployment smoke checks

- Generated Vercel URL returns HTTP 200 for the landing page
- Health and readiness endpoints report `demo` for Phase 1
- Stop search, arrivals, and accuracy views render deterministic fixture data
- Mobile and desktop layouts have no clipping or horizontal overflow
- GitHub and methodology links resolve
- A deployment with missing required live variables fails closed

The final local gate remains the full Pytest suite, Ruff, strict MyPy, and the
showcase smoke check.

## Documentation

The README gains:

- A prominent live-demo link
- A clear live-versus-demo explanation
- Vercel preview deployment instructions
- PostgreSQL and poller production topology
- Environment-variable reference without secret values
- Database migration and rollback instructions
- Custom-domain steps deferred until the generated deployment is stable

The deployment guide distinguishes Vercel web hosting from poller hosting so a
reader cannot accidentally run the continuous collector as a request function.

## Success criteria

This milestone is complete when:

1. A fresh checkout can run the deterministic showcase locally with one command.
2. The same demo experience deploys to a generated Vercel URL without secrets.
3. The public page clearly labels demo, live, stale, and insufficient-evidence
   states.
4. The application can use PostgreSQL without breaking local SQLite workflows.
5. The always-on poller and Vercel application can share one production
   database.
6. Existing history can be migrated with verified row counts and no source
   deletion.
7. Tests, Ruff, strict MyPy, and deployment smoke checks pass.
8. No custom-domain purchase, DNS mutation, or paid resource is created without
   explicit user authorization.
