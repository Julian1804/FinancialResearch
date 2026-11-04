# FR Data Guardrails

Status: `active_guardrail`
Updated: `2026-10-15`

## Entry Gate

Every source task reads `AGENTS.md`, the canonical context route, this file,
the unified storage contract, and the source policy. Before provider execution
it records successful readbacks for `fr_task_preflight`, `fr_guardrails`,
`fr_source_health`, `fr_field_semantics`, and `fr_entity_resolution`.

## Identity

- `Universe` is FR's top-level financial concept. Current Universe names come
  only from `config/fr_data_category_registry.json`; Entity, Person, and
  Document are cross-Universe subject types.
- Geography is not a Universe. China Equity means Equity × China. Region,
  market/jurisdiction, venue, instrument/security classification, board,
  listing episode, trading currency, and quote convention are orthogonal
  dimensions and must be stored or inferred only from their own evidence.
- Mainland China Equity uses Mainland China market/jurisdiction scope with SSE,
  SZSE, and BSE as peer venues. Ordinary RMB shares on all three venues are
  A-shares; SSE/SZSE foreign-currency shares are B-shares. A venue token such as
  BSE must not also become a current share/security classification. A
  BSE-specific historical object type or key remains compatibility/provenance
  only where its stable identity contract requires it.
- Hong Kong Equity uses Hong Kong market/jurisdiction scope and venue HKEX.
  H-share is one evidence-supported classification, not a synonym for all HKEX
  equity. HKEX funds/ETFs, bonds, derivatives, and other non-equities remain in
  their corresponding Universes.
- Mainland China and Hong Kong may use distinct market-specific source,
  identity/lifecycle, and update owners. They converge through neutral Equity
  standard-data, serving/publication, and Research contracts; a regional
  product grouping does not authorize one market owner to reinterpret the
  other's financial semantics.
- A physical partition, dataset/source token, historical task name, research
  display group, or the legacy `expected_universe` field must not be used as a
  direct canonical Universe mapping. Resolve the real object first and apply
  financially meaningful classifications separately.

- Stable financial subject identities include entity, Fund product/portfolio,
  Fund share class, tradable instrument, listing, and series identities; people and
  documents retain scoped IDs. Existing physical identifiers include
  `entity_id`, `instrument_id`, `listing_id`, and `series_id`. A durable
  Fund-product identifier is a required semantic role, but its physical owner
  and population belong to the next China Public Fund foundation task; this
  vocabulary closeout does not introduce or populate `fund_id`.
- A Fund product/portfolio and each Fund share class are distinct real objects.
  A Fund product must not be represented by a share-class code, listing code,
  ETF trading code, provider alias, tradable-instrument identity, or listing
  identity. Share classes, tradable instruments, and listings attach to the
  Fund product through explicit accepted relationships.
- Every fact declares `subject_type` and `subject_id`. Issuer, instrument,
  listing, and series are not interchangeable.
- External codes are scoped aliases, never replacements for stable IDs.
- Historical `provider_scoped_alias` compatibility rows may remain readable,
  but no active onboarding, batch allocation, accepted-crosswalk registration,
  or legacy normalization may assign one a durable FR subject UUID.
- A/H/ADR listings, multiple debt issues, multiple fund share classes, and
  multiple venues remain distinct subjects or series and must not be merged by
  issuer name or ticker resemblance.
- Do not create a new subject when a high-confidence existing match exists.
- Before allocation, query accepted identity crosswalks in the durable
  installation identity owner. A crosswalk must name an existing accepted
  identity decision, scoped authoritative identifier, effective interval, and
  provenance. It may recover or reuse a UUID; it may not derive one. Different
  Universe work must reuse the same accepted Entity where the proved legal
  object is the same.
- Do not force a low-confidence match. Retain it as source detail and continue
  automatic resolution.
- The authoritative subject and series registry is the first dependency for
  source-data semantic mapping. Failed matches are investigated first as
  registry coverage defects, source shell-data defects, object-type
  classification defects, alias/crosswalk defects, or matching-logic defects.
  They must not silently mint new confirmed subjects.
- Morningstar, Eastmoney, Sina, Tencent, BaoStock, AKShare-wrapped route codes,
  and other third-party identifiers are provider-scoped aliases unless an
  independent registry/crosswalk proves the FR entity, instrument, listing,
  fund share class, contract, index, currency pair, rate curve, or economic
  series identity.
- Real-world evidence establishes economic objects and events; physical FR data
  establishes current database contents. A source row, name difference,
  provider code, exchange code, or returned daily series does not by itself
  prove a distinct economic security, lifecycle boundary, or FR identity split.
  Lifecycle and identity conclusions require authoritative evidence appropriate
  to the subject, market, and event.
- Canonical aliases belong to the snapshot-local shared alias registry and are
  scoped, effective-dated, provenance-backed links to existing subjects. Code
  reuse across non-overlapping intervals is valid; an overlapping scoped alias
  to different subjects is a conflict.
- Canonical relationships belong to the shared relationship registry. New
  relationship types require a stable financial definition reference and
  authoritative provenance, but the shared contract does not pre-enumerate all
  future Universe-specific relationships.
- Snapshot locators map durable subject/series identity and query scope to
  bounded manifest members. Complete control owners are immutable checkpoints;
  routine successors persist only changed control records and hash-bound parent
  ancestry. The requested snapshot manifest, not the origin snapshot of an
  inherited locator, decides whether the exact path/layer/hash remains visible.
  Additions, replacements and tombstones are immutable successor-local state.
  Writers must not regenerate unchanged locator or derived-search populations
  solely to change a database-version identifier, and readers must not infer
  Universe or object meaning from a locator path. Recovery readers must resolve
  staged subjects against the effective checkpoint-plus-delta view rather than
  treating the newest local delta as the complete canonical subject registry.

## Semantic States

The only semantic states are:

- `semantic_confirmed`
- `evidence_insufficient_continue_auto_check`
- `semantic_conflict_do_not_promote`

Meaning is established from field labels, source documentation, interface and
statement context, units, currency, scale, sample values, related fields, and
cross-source or accounting relationships. Exact English name matching is not
enough.

Apply **Open-World Evidence Escalation（开放世界证据升级方法）** when retained
evidence cannot prove an exact meaning or confidence remains low. Build a
case-level packet, use finance/accounting/statistics/data-engineering
relationships, search direct public evidence and counterexamples, and validate
the result independently. Evidence priority is issuer/product owner/index
publisher; exchange, regulator, government, or standard setter; original
provider documentation or public page; then another public authority.
Third-party sources may corroborate but cannot alone establish a high-risk
semantic conclusion. Search snippets, diagnostic labels, and new isolation
states are not remediation outcomes.

Generalization cannot exceed the tested subject, interface, field, date or
period, document, unit, currency, scale, and series/version scope. Unresolved
cases must name the next public evidence path; user decision is reserved for
cases where bounded automated public paths are exhausted.

Income statement, balance sheet, cash flow, profitability/per-share,
valuation, shares/market-cap, fund NAV/share/flow, index constituent/weight,
bond/credit event, macro release/revision, and document metadata/content
families retain their domain-specific checks. In particular:

- never map revenue or operating income automatically to operating profit;
- never map period-end equity to average-equity ROE;
- never map current constituents to historical constituents;
- never map a notice date to an observation/report period;
- never map metadata, a URL, or a snippet to preserved original content.

## Values

Source observations retain `raw_value`, `raw_unit`, `raw_currency`,
`raw_scale`, raw field name, and `source_trace`. Promotion requires a versioned
normalization trace to `normalized_value`, `canonical_unit`, and
`canonical_currency` or explicit currency basis. Ratios, percentages,
per-share values, currency amounts, thousands, millions, and billions are not
interchangeable without explicit conversion.

## Observation And Fact Keys

`source_observation_key` includes the source identity and representation needed
to prevent replay and is stable independently of later `metric_id` mapping.
`logical_fact_key` includes the metric-required financial
subject, `metric_id`, declared economic-time role, required series dimensions, and meaningful
version/effective scope. The logical key excludes provider, interface, raw
unit/currency/scale, dataset, run ID, and source-row fingerprint.

Equal normalized observations within the metric's tolerance consolidate into
one standard fact with multiple lineage entries. Unequal same-series,
same-version observations remain classified conflicts and are never silently
selected by source priority. Domain authority applies only after subject,
series, time, version, unit, currency, and quotation alignment. Distinct economic
revisions/effective versions remain distinct facts. Direct validated values are
preferred over matching derived values; formula lineage remains available.

Native-market observations and unified-currency display values use distinct
series and an explicit versioned conversion policy. A converted display value
must not overwrite its native observation.

## Promotion

Source detail may remain when source, subject/time evidence, or field meaning is
incomplete. A standard fact requires a registry-resolved `metric_id`, explicit
subject and declared time role, complete raw and standardized representations, both keys,
and source trace. High-risk release dates, historical constituents, corporate
actions, fund flows, credit events, macro revisions, and document content have
stricter evidence requirements.

## Lifecycle And Date Precision

Normalized accepted lifecycle is Current, Historical, or Unconfirmed, based on
authoritative real-world evidence accepted into the pinned release. A proved
Historical object may have null exact `effective_end`. Evidence of a later
distinct economic episode in the same real venue/code namespace may establish
the predecessor as Historical without proving its termination day; code
equality alone does not prove two economic episodes. Temporary/parallel or
multi-currency counters, transfers and restructuring still require economic
identity reconciliation. An old release is not reclassified from today's live
source state. The database check/acceptance time is provenance, not a universal
financial `classification_as_of` column.

Lifecycle class does not automatically attribute every historical observation
to a unique episode. Demand an exact boundary only for a demonstrated overlap,
code reuse, look-ahead, or unsafe fact/episode attribution. Ambiguous residual
observations remain source detail rather than forced standard facts; do not
add canonical lifecycle states or fields for isolated unresolved cases.

An officially announced future delisting leaves an object Current until its
effective event. Suspension alone does not make it Historical. Where an
official future date is evidenced and the product supports it, use
`estimated_delisting_date` with existing announcement provenance. In the
Current projection before effective delisting, that field carries the evidenced
future date and `effective_end` remains null. Once the event becomes effective
and a later release accepts it, classify Historical, clear
`estimated_delisting_date`, and record actual `effective_end` where its date is
proved (otherwise retain null). A current object projection must never carry
both an active estimated delisting date and an actual lifecycle end. Prior
planned-date evidence remains recoverable through immutable releases and
existing provenance; do not introduce parallel planned-delisting status, date,
or source families.

Provider/source first and last observation dates are source availability and
coverage facts, not listing, security, report, or economic-series lifecycle
facts. A first observed row is not a listing/start date, a last observed row is
not a delisting/end date, and source absence is not proof that an object did
not exist or did not trade. Current date, arbitrary period end and coarse
`YYYY-01-01` placeholders are not exact lifecycle boundaries.

Schema should represent the business fact, not uncertainty about how it was
obtained. Do not add new business precision/status columns merely because
evidence is incomplete. A year-only accepted business date may use `YYYY-01-01`
only where the field definition permits year-only representation and the data
dictionary caveat is retained. Operational workflow statuses remain allowed
where they describe process state, validation state, or developer diagnostics
rather than financial reality.

One stable financial concept gets one stable canonical representation. Admit a
new permanent field/state only when its recurring financial and user value
outweighs maintenance cost and existing grain, dimension, evidence or lineage
cannot represent it. Do not collapse genuinely distinct observation,
publication, effective, last-trading and processing times merely to reduce
columns. A few unresolved historical cases do not justify framework expansion.

## Sources

- Source health is scoped by interface, date, and use case.
- Known access limits such as DCE/CZCE HTTP 412 and SGE HTTP 403 must not be
  bypassed or disguised.
- Paid, credentialed, token-gated, terminal-gated, commercial, and login-only
  sources remain excluded unless explicitly approved by the user.
- Provider failure is local to the row, instrument, or route. It does not stop
  unrelated valid work.
- AKShare is an acquisition adapter, not one economic data provider. Every
  AKShare route must retain the actual upstream owner where recoverable,
  including Eastmoney, Sina, Tencent, exchanges, index publishers, regulators,
  central banks, statistical authorities, ChinaMoney, or another named source.
- FRED, BLS, and BEA use official series, dataset, table, line, frequency,
  unit, scale, release, and revision identities in source and lineage
  contracts.
- Existing raw responses may be reused only when source, parameters, scope, raw
  location, integrity hash, and applicable date/report-period coverage are
  unambiguous. Complex or ambiguous residuals should be routed to complete
  source-family refetch instead of repeated record-level patches.

Historical information availability is an additional capability, not a prerequisite for
all data admission. Missing publication/effective timing must be stated and may
limit a read model to latest-research use, but it does not invalidate a source
observation whose own subject, economic time, value, representation, and trace
are otherwise complete.

## Historical Information State And Research Binding

Accepted revisions remain versioned rather than overwritten into parallel
`latest/original/restated/pit` columns. Ordinary current reads use latest
accepted information in the selected release; PIT/as-known research uses only
the latest version publicly available by its knowledge cutoff. A derived input
contract must say latest-revised or as-known, or it risks look-ahead.

Raw/unadjusted Equity price remains a direct fact. Adjusted price requires
accepted corporate actions plus explicit reproducible adjustment method,
anchor, inputs and lineage; total return has separate reinvestment meaning.
Use Series dimensions such as `adjustment_basis`, not provider `qfq/hfq` column
names as canonical methodology. Historical market cap uses actual price at t
and applicable shares at t, never today's shares; total/listed/tradable/free-
float shares, issuer aggregation and cross-currency FX basis remain distinct
metric meanings.

Where point-in-time research semantics matter, keep the economic/reference
time, event effective time, actual publication or knowledge time, and official
information-version identity separate. A later official revision supersedes an
earlier information state only for a knowledge cutoff that can see the later
publication. Economically different Series, including unadjusted and adjusted
prices, are not revisions of one fact.

An immutable research input records its database-version ID, manifest SHA-256,
knowledge cutoff, exact query and subject-selection rule, feature and label
definitions, code/parameter/environment identity, ordered columns and rows, and
a deterministic input digest. Reproduction resolves the named immutable
database version rather than mutable current state and recomputes the digest.
`backend/app/core/research_binding.py` owns the small shared representation and
hash/cutoff invariants; Universe-specific code continues to own the financial
interpretation and is not replaced by a universal decision engine.

## Active Terminology

Active contracts use `metric_id`, `source_observation_key`,
`logical_fact_key`, source observations/source detail, standard facts, and read
models. Legacy field/key names may appear only in immutable historical evidence
or the bounded FR_DATAFOUNDATION2 migration reader. Active new-write validation
rejects them.
