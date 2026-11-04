# FR Read Model Contracts

Routing status: `active_contract`
Authority: release-bound logical projection, grain, fields, filters, bounds,
pagination, and export scope; not ordinary product navigation.
Updated: `2026-10-25`

## Accepted Stage A Product Projection

The accepted Stage A Data Product contract is an application projection over
the existing release-bound Fund and Equity query owners, not a new authoritative
fact or read-model layer. One pinned composite release binds all selected fields;
returned daily dates form a cardinality-safe union, and each field has a
separate retrieval/availability state. Logical catalog presence comes from the
fixed release manifest, not from mounted routes or physical fact-row counts.
Its versioned dictionary describes exposed fields; unknown logical counts
remain unknown, while identity previews return exact filtered logical counts.
Fund discovery resolves all matching accepted control layers before server-side
filtering and continuation. Owned local jobs export all matching identity rows,
including a permitted complete identity dataset, or all returned rows for one
selected daily subject/field interval in bounded windows. Bounded preview/CSV
is not a complete dataset. Durable Fund/share-class/listing identities, rather
than external codes, own drill-down. The lifecycle projection classifies only
accepted identities using manifest-bound Fund historical ownership and Equity
reality evidence at the Product, Share Class or Listing grain. Ordinary identity
browsing defaults to Current; direct search and complete identity exports retain
all accepted states. Historical may have a null exact end; scheduled official
delisting does not become an actual end until a later release accepts it.
`Unconfirmed` remains explicit and discovery candidates stay outside the formal
population. No universal `classification_as_of` field is required. Ordinary provenance is
identified only where the release-bound point proves a source family; otherwise
it is explicitly unavailable. Stage A acceptance does not authorize Stage B or
claim that separate frontend integration is complete.

## Common Contract

Read models project from the logical standard-fact layer through
`logical_fact_key` and the single metric registry. They expose stable model and
snapshot versions, explicit subject identity and relationships, declared
economic-time roles, `metric_id`, normalized value/unit/currency, necessary
dimensions, source-observation lookup reference, and user status. Where a
materialization-completion timestamp is retained, it is process metadata:
it is not observation time, disclosure time, source freshness, or a proved
scope-level `数据核查日期` (data check date).

Every physical query declares bounded economic-time or report-period limits,
subject scope, metric/field set, and a server-enforced row or page bound.
These are application/backend safety contracts, not mandatory ordinary UI
controls. Ordinary service availability is `available` or `unavailable`;
field-level missing observations and failed retrieval remain distinguishable
in result detail. Provider and raw
representation do not distinguish read-model fact rows.

No builder implements another metric alias, normalization, source-key, or
logical-key system. Read models are reproducible projections and never become a
second authoritative layer.

## Read-Model Catalog

Each catalog entry contains:

- `read_model_name`, `contract_version`, and `materialization_version`;
- `snapshot_id`, `logical_contract_version`, and `metric_registry_version`;
- supported subject types, fields/metrics, economic-time roles, and bounds;
- maximum per-request row/page bound and ordering contract (execution safety,
  not the user's selectable financial-history range);
- observation coverage with its declared time role, separately identified
  process materialization time where proved, and available/unavailable status;
- source lookup capability and reproducible builder identifier.

The catalog and API do not expose a physical file, partition directory, SQLite
or DuckDB file, drive letter, or control backend. The physical adapter resolves
the pinned snapshot only after a request satisfies this contract.

## Registered Models

- `equity_daily_panel_v1`
- `equity_latest_snapshot_v1`
- `equity_field_coverage_v1`
- `market_index_daily_panel_v1`
- `fund_nav_daily_panel_v1`
- `financial_kpi_panel_v1`
- bounded foundation registrations for bonds, FX, macro,
  commodities/derivatives, documents, and identity/source-detail projections

Pre-migration materializations remain historical or `refresh_required`. The
active V1 product boundary is the composite release and its embedded Fund and
China Equity serving contracts described below; old catalog names do not select
the active release.

## Historical Information Availability Rules

Observation/report period is not release availability. Where complete timing
evidence exists, historical-information reads enforce publication/effective
boundaries and version scope. Historical information availability is additive rather than a universal admission
prerequisite. Current-only constituents, profiles, and source snapshots are not
presented as historical observations.

Frontend code must not scan standard facts, source observations, raw domain
tables, or physical Parquet paths directly.

## Current Published V1 Query Boundary

The current active pointer selects the authoritative immutable composite
binding; no static release ID in this contract can select it. The release
binds component snapshots and release-pinned minimum query contracts directly,
without an independent mutable read-model pointer.

- China Public Fund resolves typed Fund/product/share-class/instrument/listing
  identity and serves bounded NAV, accumulated NAV, close, volume, and traded
  amount Series through manifest-proved locators.
- China-region Equity uses accepted Mainland SSE/SZSE/BSE and Hong Kong HKEX
  market-specific identity owners to resolve a lifecycle-effective code/venue
  episode to one durable listing/instrument/entity chain. Supported release
  members serve bounded accepted unadjusted daily OHLCV/amount/turnover Series.
  Unsupported adjustment bases, KPI, document, corporate-action inference,
  provider-code identity, and arbitrary SQL fail explicitly. Availability
  remains pinned-release, subject, metric, and interval specific.

Every ordinary request pins one immutable active release. Review access to a
validated unpublished state must be explicit and cannot alter ordinary active
serving. `alias_effective_date` selects lifecycle-effective aliases only; it is
not observation time, knowledge cutoff, publication time, revision time,
source-availability time, or physical-representation time.

READMODEL4/READMODEL7 and their snapshot IDs remain historical migration,
compatibility, or evidence identifiers. They do not override the active V1
release. Other registered models are available only when the active release or
a separately explicit review contract binds them; registration alone is not a
production-serving claim.
