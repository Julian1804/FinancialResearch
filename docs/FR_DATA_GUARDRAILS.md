# FR Data Guardrails

Status: `active_guardrail`
Updated: `2026-07-24`

## Entry Gate

Every source task reads `AGENTS.md`, the canonical context route, this file,
the unified storage contract, and the source policy. Before provider execution
it records successful readbacks for `fr_task_preflight`, `fr_guardrails`,
`fr_source_health`, `fr_field_semantics`, and `fr_entity_resolution`.

## Identity

- Stable financial subject IDs are `entity_id`, `instrument_id`, `listing_id`,
  and `series_id`; people and documents retain scoped IDs.
- Every fact declares `subject_type` and `subject_id`. Issuer, instrument,
  listing, and series are not interchangeable.
- External codes are scoped aliases, never replacements for stable IDs.
- A/H/ADR listings, multiple debt issues, multiple fund share classes, and
  multiple venues remain distinct subjects or series and must not be merged by
  issuer name or ticker resemblance.
- Do not create a new subject when a high-confidence existing match exists.
- Do not force a low-confidence match. Retain it as source detail and continue
  automatic resolution.

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

## Sources

- Source health is scoped by interface, date, and use case.
- Known access limits such as DCE/CZCE HTTP 412 and SGE HTTP 403 must not be
  bypassed or disguised.
- Paid, credentialed, token-gated, terminal-gated, commercial, and login-only
  sources remain excluded unless explicitly approved by the user.
- Provider failure is local to the row, instrument, or route. It does not stop
  unrelated valid work.

Historical information availability is an additional capability, not a prerequisite for
all data admission. Missing publication/effective timing must be stated and may
limit a read model to latest-research use, but it does not invalidate a source
observation whose own subject, economic time, value, representation, and trace
are otherwise complete.

## Active Terminology

Active contracts use `metric_id`, `source_observation_key`,
`logical_fact_key`, source observations/source detail, standard facts, and read
models. Legacy field/key names may appear only in immutable historical evidence
or the bounded FR_DATAFOUNDATION2 migration reader. Active new-write validation
rejects them.
