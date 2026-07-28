# FR Read Model Contracts

Routing status: `active_contract`
Authority: unified bounded storage-neutral read-model interface.
Updated: `2026-07-22`

## Common Contract

Read models project from the logical standard-fact layer through
`logical_fact_key` and the single metric registry. They expose stable model and
snapshot versions, refresh time, explicit subject identity and relationships,
declared economic-time roles, `metric_id`, normalized value/unit/currency,
necessary dimensions, source-observation lookup reference, and user status.

Every query declares bounded economic-time or report-period limits, a subject
universe, metric/field set, and row limit. Status is `available` or
`unavailable`; diagnostics remain developer-only. Provider and raw
representation do not distinguish read-model fact rows.

No builder implements another metric alias, normalization, source-key, or
logical-key system. Read models are reproducible projections and never become a
second authoritative layer.

## Read-Model Catalog

Each catalog entry contains:

- `read_model_name`, `contract_version`, and `materialization_version`;
- `snapshot_id`, `logical_contract_version`, and `metric_registry_version`;
- supported subject types, fields/metrics, economic-time roles, and bounds;
- maximum row limit and ordering contract;
- freshness, coverage, and available/unavailable status;
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
active catalog is the accepted READMODEL4 release named below.

## Historical Information Availability Rules

Observation/report period is not release availability. Where complete timing
evidence exists, historical-information reads enforce publication/effective
boundaries and version scope. Historical information availability is additive rather than a universal admission
prerequisite. Current-only constituents, profiles, and source snapshots are not
presented as historical observations.

Frontend code must not scan standard facts, source observations, raw domain
tables, or physical Parquet paths directly.

## READMODEL4 Publication

STORAGEFOUNDATION2 is accepted only as the completed one-pass migration
checkpoint. STORAGEFOUNDATION2R produced corrected unpublished candidate
`frsf2r_20260721T173814Z_a807549b1c88` with assertion-based source/reverse
lineage, multi-source, version, conflict, cross-domain, coverage, H-share,
A/H/ADR, bond, and physical-locator validation. Meaningful current-only or
non-final source-detail versions remain metadata and are not exposed as
historical accepted facts.

STORAGEFOUNDATION3 published the foundation snapshot and R3 subsequently
published READMODEL4 release
`readmodel4_frrem1r3_20260722T190906Z_7f8820854863_v1` as one composite serving
release. All six primary models are available. Fixed-income, FX,
commodities/derivatives, identity graph, source-detail/lineage, conflict, and
coverage projections are bounded registered surfaces. Separate macro,
historical index membership, corporate-action, and document models are
unavailable with explicit reasons; no rows are invented.

Observation/report period remains distinct from publication availability.
Financial KPI is latest-research ready but does not have general historical
information availability. Current constituent snapshots remain current-only. Meaningful source
versions stay source detail because accepted fact variants are zero. The
active snapshot is `frrem1r3_20260722T190906Z_7f8820854863` with manifest
SHA-256 `1a9f3c1e1a6f40549daf1c4908107dc7f4c01a3e9a7a689f8874f22aeb1d99c5`.

## READMODEL7 Candidate Review Status

Remediation3R2 produced accepted unpublished READMODEL7 release
`readmodel7_frrem3r2_20260728T031358Z_88b9fa67d6c7_v1`. It is not active and
must not be routed to product/API consumers until a later publication task
changes the active composite pointer. Release-candidate audit may load its
manifest and perform bounded physical validation from the unpublished release
path.

READMODEL7 compatibility panels can be sampled through the same field/subject
gateway contract where the manifest declares query metadata. The lossless
logical-fact history projection is retained for validation and lineage review;
it is physically readable with bounded Parquet reads, but it is not a generic
gateway query surface unless a later contract adds the required subject-field
metadata.
