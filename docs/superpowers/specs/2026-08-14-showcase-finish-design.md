# U-Mich Transit Showcase Finish — Design

**Date:** 2026-08-14
**Status:** Approved for planning
**Audience:** Technical employers and recruiters; U-M students and prospective users

## Product statement

Magic Bus publishes live arrival predictions. U-Mich Transit measures how those
predictions perform, learns recurring errors, and gives riders more honest
guidance through a local web dashboard and an MCP server.

The finished project is a reliability-led showcase. Its technical claim,
student-facing experience, and conversational MCP interface tell one story:

> Magic Bus said four minutes. Historical evidence suggested nine. The bus
> arrived in ten.

The project must demonstrate this claim honestly. Attractive presentation is
important, but it cannot imply that adjusted predictions improve accuracy
unless a chronological holdout evaluation supports that conclusion.

## Goals

1. Make the reliability methodology defensible and reproducible.
2. Show published and adjusted predictions in a polished, mobile-friendly local
   dashboard.
3. Report whether the adjustment improves held-out prediction accuracy.
4. Expose the same live and analytical capabilities through a focused MCP
   interface.
5. Provide a deterministic demo experience when live service or sufficient
   history is unavailable.
6. Make the repository easy for a recruiter to run, understand, and review.

## Non-goals

The following are deferred beyond this 1–2 week finish:

- Public hosting and production operations
- Authentication, user accounts, and cross-device favorites
- TheRide/AAATA or other agency integration
- Transfers or full journey planning
- Postgres migration
- Native mobile applications
- Maps and elaborate animations
- Opaque machine-learning models

The local architecture should not prevent later hosting, but this work will not
add hosting infrastructure prematurely.

## Showcase success criteria

A reviewer can:

1. Start a deterministic showcase with one documented command.
2. Search for a stop and see upcoming buses.
3. Compare the published ETA with the reliability-adjusted ETA.
4. Understand an adjustment from its historical bias, sample size, aggregation
   scope, and confidence.
5. View published-versus-adjusted accuracy on held-out observations.
6. Ask equivalent questions through MCP and receive concise, evidence-backed
   answers.
7. Understand the data flow, limitations, and engineering decisions from the
   README and architecture documentation.

The repository remains green under tests, Ruff, and strict MyPy.

## Architecture

The existing separation remains authoritative:

- `core/` owns normalized upstream records, storage, matching, adjustment,
  evaluation, and shared service responses.
- `poller/` collects predictions and positions, detects arrivals, and refreshes
  derived outcomes and statistics.
- `web/` contains only HTTP presentation, static UI assets, and browser-local
  preferences.
- `mcp_server/` contains only MCP registration, input validation, and response
  presentation.

Neither `web/` nor `mcp_server/` may contain SQL, matching logic, reliability
math, or direct upstream payload handling. Both consume `TransitService`.

The data flow is:

```text
BusTime predictions ──┐
                     ├─> SQLite raw observations ─> matched outcomes
Vehicle GPS ─────────┘                              │
                                                    ├─> reliability profiles
                                                    └─> holdout evaluation
                                                              │
                                ┌─────────────────────────────┴──────────┐
                                ▼                                        ▼
                         Web dashboard                              MCP tools
```

## Prediction outcomes

### Matching rule

Each detected arrival is matched to at most one prediction for the same
vehicle, stop, and route.

- Target prediction horizon: 300 seconds before actual arrival.
- Allowed capture-time tolerance: plus or minus 90 seconds around that target.
- Selection: the eligible prediction whose capture time is closest to the
  target capture time.
- A prediction cannot be reused for multiple outcomes.
- Predictions with impossible ordering, missing identifiers, or a predicted
  arrival earlier than their capture time are excluded and counted as data
  quality rejections.

This replaces the current newest-prediction-in-the-previous-five-minutes rule,
which tends to evaluate easier last-minute predictions rather than a consistent
rider decision point.

### Stored outcome

A derived prediction outcome records:

- Prediction and arrival identifiers
- Route, stop, and vehicle identifiers
- Prediction capture, predicted arrival, and actual arrival timestamps
- Prediction horizon in seconds
- Signed error in seconds: actual minus predicted
- Absolute error in seconds
- Arrival detection method
- Match rule version

The derived table is rebuildable from raw predictions and arrivals. Raw
observations remain the source of truth.

## Reliability adjustment

The adjustment remains a transparent historical-bias correction, not an opaque
model.

### Aggregation hierarchy

Profiles are evaluated from most specific to broadest:

1. Route + stop + local weekday + local hour
2. Route + stop + local hour
3. Route + local weekday + local hour

Local bins use `America/Detroit`. The first qualifying profile is selected.
No broader global or cross-route correction is applied because it would be hard
to explain to a rider and could mix unrelated service behavior.

### Correction and confidence

- Correction: median signed historical error for the selected profile.
- Safety clamp: at most plus or minus 600 seconds.
- **High confidence:** the exact route/stop/weekday/hour profile has at least 30
  outcomes.
- **Medium confidence:** a broader qualifying profile has at least 20 outcomes.
- **Low confidence:** no profile qualifies; return the published ETA unchanged.

Every adjusted arrival exposes the correction, aggregation scope, sample count,
confidence, and a short reason such as "this route is typically 3 minutes late
at this stop around this hour."

These initial thresholds are product rules, covered by tests and centralized as
named configuration constants so later empirical tuning is explicit.

## Honest accuracy evaluation

The evaluation uses only matched outcomes and prevents training/test leakage.

1. Sort outcomes chronologically.
2. Require at least 100 total outcomes for an overall evaluation.
3. Use the oldest 80 percent as training data and the newest 20 percent as the
   holdout set.
4. Build reliability profiles from training outcomes only.
5. Apply those frozen profiles to each holdout prediction.
6. Compare published and adjusted errors against the actual arrival.

Route-level metrics are shown only when a route has at least 20 holdout
outcomes. Otherwise it is marked as insufficient evidence.

The report includes:

- Mean absolute error
- Median absolute error
- Signed mean error (bias)
- Percentage of predictions within two minutes
- Sample counts
- Training and evaluation date ranges
- Results overall and by qualifying route
- Match and model version identifiers

The UI and MCP must state whether the adjusted model improved, tied, or worsened
each metric. They must never hide a negative result. The report is a versioned,
derived artifact and is refreshed after reliability profiles are recomputed.
The headline classification uses mean absolute error: a reduction of at least
one second is `improved`, an increase of at least one second is `worsened`, and
anything between those bounds is `tied`. Evaluation builds its own frozen
training profiles; it never reuses operational profiles trained on the holdout
period.

## Storage changes

An Alembic migration adds only derived storage required for fast, reproducible
reporting:

- `prediction_outcomes` for versioned matches
- `reliability_profiles` for the three aggregation scopes
- `evaluation_reports` for generated report metadata and structured metrics

Derived rows may be deleted and rebuilt without losing raw observations.
Indexes support vehicle/stop matching, chronological evaluation, and
route/stop/time profile lookup. SQLite remains the only supported database for
this milestone.

## Shared service API

`TransitService` remains the single application boundary and gains typed,
serializable response models for:

- Live arrivals with adjustment explanations and data freshness
- Overall and route-level prediction accuracy
- Evaluation status when evidence is insufficient
- Data-health metadata used by both presentation layers

The service returns stable domain values; human-readable summaries stay in the
web and MCP presentation layers.

## Dashboard

The dashboard is a responsive, mobile-first single page with two primary views.

### Live board

- Searchable and browser-saved stops
- Per-stop walk time and "when to leave" guidance
- Route color, published ETA, adjusted ETA, and clock time
- High/medium/low confidence indicator
- A concise explanation of the adjustment
- Last live observation time and a stale-data warning

Low confidence displays only the published ETA and explains that there is not
enough history for an adjustment.

### Accuracy

- A headline comparison of published and adjusted mean absolute error
- Evaluation sample count and date range
- Within-two-minutes and bias comparisons
- A compact route-level table
- Several deterministic prediction-versus-reality examples
- Clear improved/tied/worsened language rather than celebratory styling by
  default

The page prioritizes typography, spacing, route identity, responsive layout,
loading states, and accessible contrast. Maps and nonessential animation are
out of scope.

## MCP surface

The showcase MCP surface contains:

- `list_routes`
- `find_stops`
- `get_arrivals`
- `route_reliability`
- `prediction_accuracy`

`get_arrivals` includes adjustment reason, aggregation scope, confidence,
sample size, and freshness. `prediction_accuracy` accepts an optional route
filter and returns the held-out metrics used by the dashboard. Stop-level
evaluation is deferred because the holdout samples would usually be too sparse
to support a defensible comparison.

The incomplete `plan_trip` tool is removed from public registration and
showcase documentation. Its current approximation does not validate direction
or calculate travel time, so exposing it would weaken the project's credibility.
Full trip planning remains a documented future capability.

MCP tools return both concise summaries suitable for conversation and structured
fields suitable for inspection. Tool descriptions state evidence limits and do
not claim that adjusted predictions are better unless the report supports it.

## Deterministic demo mode

Demo mode exists for reviewers, evenings without service, upstream outages, and
machines without a BusTime key.

- Versioned JSON fixtures contain a small synthetic-but-realistic history, live
  arrivals, and known evaluation results.
- A demo seed command creates a separate SQLite database from those fixtures.
- Seeding shifts the fixture's reference timeline relative to startup so demo
  arrivals remain upcoming while all historical intervals and expected metrics
  remain deterministic.
- `uv run umich-transit-demo` seeds or refreshes that database and starts the
  dashboard locally.
- The demo page displays a persistent "Demo data" banner.
- Demo data never shares a database with live data and is never selected
  silently.

The README labels demo results as illustrative. Real performance claims must be
generated from real collected observations.

## Error and data-quality behavior

- **BusTime unavailable:** retain the last successfully rendered live board in
  the browser, show a retry notice, and do not replace it with empty data.
- **Stale observations:** show their age and mark the board stale after a
  configurable threshold that defaults to five minutes.
- **No arrivals:** show a normal no-service state, distinct from an error.
- **Insufficient history:** show published predictions without adjustment.
- **Insufficient evaluation data:** explain the minimum evidence requirement and
  withhold comparative claims.
- **Rejected matches:** count rejection reasons in data-health output; do not
  silently include questionable rows.
- **Corrupt or missing demo database:** rebuild it from versioned fixtures or
  report an actionable startup error.

Logs must not expose the BusTime API key.

## Testing and verification

### Unit tests

- Fixed-horizon matching and tolerance boundaries
- Prediction reuse prevention and rejection reasons
- Local-time aggregation scopes
- Median correction, clamp, and confidence fallback
- Chronological split and leakage prevention
- Accuracy metrics and improved/tied/worsened classification
- Demo fixture determinism

### Integration tests

- Derived outcomes and profiles rebuilt from seeded raw observations
- Service response models for high, medium, and low confidence
- Dashboard live and accuracy endpoints
- MCP arrival and accuracy formatting
- Stale, upstream-error, and insufficient-evidence states
- Alembic migration from the current schema

### Showcase smoke check

One documented command verifies:

- Demo database creation
- Schema version
- Web health and JSON endpoints
- MCP server construction and tool registration
- Static asset availability

The final verification gate runs the complete test suite, Ruff, strict MyPy,
and the showcase smoke check.

## Documentation and demonstration

The README is rewritten around the outcome rather than the implementation
inventory. It includes:

- The project claim and an automatically generated accuracy result or a clearly
  labeled insufficient-evidence state
- A short demo GIF or screenshots
- One-command demo instructions
- Live-data setup instructions
- Architecture and methodology diagrams
- MCP client configuration and sample questions
- Honest limitations and deferred work

A two-minute demo script follows this sequence:

1. Start deterministic demo mode.
2. Open a stop and compare published with adjusted guidance.
3. Show the accuracy view and chronological holdout methodology.
4. Ask the same question through MCP.
5. Briefly show the shared core architecture and automated verification.

## Implementation order

1. Outcome matching and schema migration
2. Reliability profiles and chronological evaluation
3. Shared service response models and data-health API
4. Dashboard live-board and accuracy redesign
5. MCP accuracy tool and focused tool surface
6. Deterministic demo mode and smoke check
7. README, diagrams, screenshots, and demo script
8. Full verification and cleanup

This order proves the central claim before investing in presentation and keeps
both interfaces aligned through the shared service boundary.
