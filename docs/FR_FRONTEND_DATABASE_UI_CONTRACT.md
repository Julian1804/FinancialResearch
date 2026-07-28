# FR Frontend Database UI Contract

Routing status: `active_contract_plan`
Authority: planned frontend database browsing and bounded query interface. It
does not override `AGENTS.md`, `FR_CURRENT_STATE.md`, or `FR_NEXT_TASK.md`.
Updated: `2026-07-22`
Implementation authorized now: `no`

## Current Implementation Status

The repository currently contains a static dashboard skeleton under
`frontend_web/src/dashboard_v1/`. The project-wide stage release-candidate
audit treats those pages as inspectable frontend evidence and captures
screenshots, but it does not promote the skeleton to a completed product UI.

The current FastAPI app exposes a small route set, while the static frontend
references broader `/api/...` calls that are not yet wired to backend routes.
That gap is an explicit release-readiness finding. Normal users must not be
shown READMODEL7 as active and must not receive physical paths, arbitrary SQL,
raw payloads, provider parameters, or developer diagnostics through the static
UI.

## User Status Contract

Normal user-facing data status has exactly two values:

- `available`
- `unavailable`

Provider health, source gaps, mapping gaps, extraction anomalies, revisions,
recovery conditions, and backend review states are developer-only diagnostics.
They must not appear as additional normal-user status values.

## Access Boundary

- Frontend pages query versioned read models and bounded catalog/coverage APIs.
- Frontend code must not query `standard_facts` directly.
- Frontend code must not query raw domain tables such as
  `stock_trading_records`, `fund_trading_records`, or
  `financial_api_records` directly.
- Backend services resolve read-model rows to `logical_fact_key`,
  `source_observation_key`, and
  `source_trace` back-references.
- This contract implements no UI, API, read model, model, simulation, backtest,
  trading action, or trading advice.

## Page 1: Data Domains

Purpose: show business domains such as A-share equity, Hong Kong equity, market
index, fund/ETF, financial KPI, person corpus, and simulation inputs.

Visible fields:

- domain name and concise description;
- `available` or `unavailable`;
- supported read-model count;
- bounded coverage summary and last refresh time.

Developer diagnostics are excluded from the normal page. Selecting a domain
opens its read-model catalog, not a standard-fact table browser.

## Page 2: Tables / Read Models

Purpose: list versioned query surfaces defined by
`FR_READ_MODEL_CONTRACTS.md`.

Visible fields:

- read-model name and version;
- purpose and status;
- key grain, supported date/period range, fields, and refresh timestamp;
- primary filters and row-limit policy.

Physical standard-fact/source-observation tables may appear only in a developer-only
diagnostic inventory and must be marked `direct_frontend_query_allowed=false`.

## Page 3: Field Dictionary

Purpose: define fields before users construct queries.

Visible fields:

- `metric_id` and display label from the unified metric registry;
- definition, unit, currency, scale, frequency, and applicable domain;
- direct/derived indicator where relevant;
- `available` or `unavailable` for the selected read model and scope;
- source-trace availability indicator without exposing raw payloads.

Backend mapping and provider diagnostics remain developer-only.

## Page 4: Coverage

Purpose: display bounded instrument, field, and date/report-period coverage.

Visible fields:

- domain/read model;
- entity, instrument, listing, or series count when safely derived;
- field count and covered row count;
- minimum/maximum date or report period when available;
- `available` or `unavailable`.

Unknown exact counts are displayed as unavailable or omitted, not estimated as
facts. Backend detail may explain that a grouped scan was intentionally not run.

## Page 5: Query Builder

Purpose: construct bounded reads against one approved read model.

Every query requires:

- one read-model version;
- a bounded date/report-period range;
- an explicit `subject_type`/`subject_id` universe;
- an explicit field set;
- an explicit row limit.

Recommended defaults are 1,000 rows and a maximum of 100,000 rows per request.
Larger exports require a separately authorized asynchronous workflow. The query
builder rejects unbounded requests, wildcard-all universes, direct standard-fact
SQL, unsupported fields, and missing historical-information controls where historical availability
matters.

## API Response Contract

Successful bounded responses include:

- read-model name/version and refresh timestamp;
- applied filters and row limit;
- rows plus field/unit/currency/scale metadata;
- coverage/status summary;
- source dataset and source-trace lookup references;
- truncation or pagination metadata.

Normal-user errors use clear unavailable/bounds messages. Detailed provider,
mapping, SQL, recovery, and lineage diagnostics are restricted to developer
logs or admin-only evidence.

## Security And Performance

- Parameterized APIs only; no arbitrary SQL from the browser.
- Read-model allowlist, field allowlist, date bounds, universe bounds, and row
  limits are enforced server-side.
- Query timeouts, pagination, cancellation, and audit metadata are required.
- Raw payloads, credentials, local paths, provider parameters, and internal
  error excerpts are never returned to normal users.

## Acceptance Gate

A UI task must start from an explicit page-level UI contract and then implement
and test all visible text, DOM/state behavior,
screenshots, responsive layouts, bilingual text where relevant, availability
states, bounded API behavior, and source back-references. This planning task
authorizes none of those implementation actions.
