# FR Frontend Database UI Contract

Routing status: `active_frontend_read_boundary`
Authority: current ordinary frontend product structure and bounded financial-
data interaction contract. It does not override `AGENTS.md`,
`FR_CURRENT_STATE.md`, or `FR_NEXT_TASK.md`.
Updated: `2026-10-25`

Ordinary product design follows user financial task -> real financial semantics
-> product expression -> application/backend contract -> schema/storage. Reuse
mature financial-product interaction patterns unless FR has a material semantic
or reproducibility reason to differ. Internal IDs, manifests, paths, provider
diagnostics, row limits and API/read-model architecture are secondary technical
evidence, not ordinary workflow concepts.

## Database-First Product Contract Direction and Stage A Boundary

The accepted product direction is a governed financial database first, with
research built on it. Normalized identities and facts protect financial truth;
ordinary Fund/Equity views recombine them only through cardinality-safe,
release-bound projections. Data Explorer is the deliberate logical-dataset
inspection path, not a browser over physical Parquet, SQLite, control tables,
or internal read-model names. A logical catalog may show a governed family as
present while clearly withholding preview/export when no user-safe contract
exists. The same catalog version owns its Data Dictionary. Multi-field daily
Data tables union actually returned observation dates, never forward-fill, and
distinguish a missing cell from a failed field retrieval; comparative
Statistics keeps its separate common-date calculation semantics. Export must
retain the fixed release, selected object/fields, declared row grain, and
scope; a bounded preview is not an entire-dataset export.

Backend Stage A is accepted as a release-bound product/read contract; separate
frontend integration and acceptance remain downstream. The frontend must not
derive Current from a null end date or stale source status. No global
`classification_as_of` field is required. The accepted contract includes
complete Fund search continuation and release-pinned local
export jobs for identity datasets and selected daily intervals. Whole-dataset
daily export across every object is not exposed. A human-readable provider is
shown only when the release-bound point proves one; otherwise attribution is
explicitly unavailable. Frontend must not derive its own lifecycle class.
Backend Stage B is accepted at `a92ff65d463a859c329b9c1fdae66509bd073be0`.
It owns the configured Update denominator, independent financial Update Scope
results, durable publication authority, and per-scope `数据核查日期` readback.
The frontend candidate integrates those reads under Settings and awaits
independent acceptance; this does not imply UI freeze, RC, or Public Release.

## Stable Product Architecture And Current Surface

The active ordinary-user hierarchy is `Home`, `Data` (Funds, Equities),
`Research` (Statistics), and secondary `Settings` (Data Update, Data Status)
and `Advanced` (diagnostics/review). Fund and Equity are Data Universes;
regional coverage is context within each workflow. Statistics may expose the
currently supported comparative calculations but is not defined by their
historical API name. Models, Simulation, and Parse Lab are future product
placements, not current ordinary routes. Home is a concise landing/status
surface, not a second sitemap. Morningstar remains outside ordinary navigation.
Every implemented subpage or object detail has a visible product-level return
path. Ordinary result hierarchy starts with financial identity, metric and
meaning, then result, range/unit/currency, observation coverage, provenance,
and finally technical identifiers. Query-result freshness, source-check time,
operation completion, and availability are distinct; unknown/not-proven dates
are never synthesized.

The long-term ordinary product architecture is user-oriented:

```text
Home
Data
  data discovery, validation, governed modification, export
Research
  research tools and saved Research Artifacts
Settings
  updates, data status, connections, jobs, runtime/storage controls
Advanced
  diagnostics and review tools
```

`Home` is the landing and continuity surface, not a separate financial domain.
Fund and Equity are Data content classifications, not permanent top-level
product domains. This hierarchy assigns future capabilities to stable product
locations; it does not claim that every Research or Settings feature is
implemented.

The supported dependency-free frontend remains under
`frontend_web/src/dashboard_v1/`. Its hash-route names are implementation
compatibility, not the product taxonomy. Existing Fund, Equity, Research,
status, and advanced capabilities are reused under the hierarchy above;
Data itself is object/data discovery rather than a renamed update console.

The supported local gateway may retain the standalone Morningstar credential
panel for explicit local access, but ordinary navigation does not advertise it.

Retained Modeling, Simulation, Dashboard, Project, App, plug-in, generic table
browser, and old HTML code is non-current implementation history. It is not an
ordinary route, product promise, serving authority, or acceptance target.
Accepted ordinary-user verification does not turn retained prototypes into
product capabilities.

## Application/Product Layer

Frontend workflows consume stable product/application APIs rather than
mirroring backend modules, tables, manifests, or physical storage. The layer
between the frontend and domain/capability services may coordinate owners for
one researcher workflow, produce presentation-oriented projections, enforce
product policy, deduplicate equivalent work, batch compatible requests, request
only needed fields/ranges, reuse bounded request/session results, and expose a
stable product API.

It does not own canonical financial truth, reinterpret Fund/Equity semantics,
allocate durable identity, become a universal financial object model, persist a
second fact database, or hide an underlying structural scan behind a cache.
Physical grouped reads, serving indexes, partitions, and release artifacts
remain owned by the relevant backend/domain/storage layer.

The durable researcher workflow is:

```text
discover/check -> update when needed -> verify -> select tool and inputs
-> execute -> inspect -> adjust -> rerun -> save -> resume -> export
```

The frontend optimizes usability, continuity, understandable waits/errors, and
low repeated effort. Backend services optimize financial correctness,
maintainability, upgradeability, testability, and extensibility. Their stable
application/API contracts are the boundary between those goals.

## Current Serving And Access Boundary

The ordinary Fund and China Equity pages use their current release-native query
services. They do not ask users to choose a generic read-model version and do
not expose Tables/Read Models, Field Dictionary, Coverage, or universal Query
Builder as the current product architecture.

- Startup may call only current readiness and capability-catalog endpoints.
- Fund calls only the current `/api/funds/*` release/session/search/subject/
  timeseries/non-promoted/update contracts.
- China Equity calls only the current `/api/equity/china/*` session/search/
  resolve/timeseries contracts and the governed Equity update entry. Existing route or
  module names containing `a-share` are compatibility interfaces, not product
  taxonomy or evidence of Hong Kong ownership.
- Browser networking is centralized in the current API client. Page modules do
  not call removed dashboard, modeling, simulation, project, workspace, SQL, or
  generic catalog routes.
- The frontend never reads `standard_facts`, source-observation storage, Parquet,
  SQLite, raw provider payloads, manifests, or local filesystem paths directly.
  Current backend services own physical resolution and bounded readback.
- The accepted Research1 `/api/research` comparative-Series backend is a future
  Research integration boundary, not yet a rendered page. This contract does
  not authorize an arbitrary new API, generic read-model product, SQL browser,
  new Universe, model, simulation, backtest, trading action, or investment-
  advice surface.

Backend read models may remain internal implementation components or future
serving contracts where separately accepted. Their existence does not reinstate
the retired generic read-model/table-browser user model.

## Shell, Navigation, And State

Global shell state owns language, current route, readiness, backend capability
catalog, and the shared configuration/lifecycle readback. Fund and China Equity
own their workflow state. Late responses from a prior route visit cannot
replace the currently rendered route or its user action state. A new
Universe joins Data as a content capability with explicit identity,
lifecycle, Series, availability, release, update, and error contracts; it does
not require another standalone mini-app or a speculative universal framework.

Ordinary navigation exposes only usable current capabilities. Research and
Settings receive visible product locations for their accepted current
workflows, with technical/review tools separated under Advanced. The
Morningstar credential panel is not an ordinary navigation destination.

## Service And Data Status

Top-level normal-user service status has exactly two confirmed meanings:

- `available`
- `unavailable`

When the current service or lifecycle read fails, current availability is
unconfirmed. A transport failure does not change the last known configuration
or establish an empty financial search result. Retained check records must be
identified as last-read evidence until a successful refresh.

Fund may additionally show the financially defined release-contract data states
`available`, `source_gap`, `lifecycle_not_applicable`,
`known_nonpromoted_history`, and `true_empty` with user-facing explanations.
China Equity shows `available` or `unavailable` for the exact listing, metric,
and requested interval. Provider health, mapping detail, recovery conditions,
internal workflow states, and raw diagnostics are not financial data states.

Unknown coverage, denominator, freshness, or completeness is omitted or stated
as unavailable/unknown. The frontend must not infer external-Universe coverage
from FR inventory, provider first/last observation, a non-empty response, or a
successful query.

## Immutable Release Interaction

Every Fund and China Equity interaction establishes one immutable serving or
explicit review binding. Every financial response is checked against that
binding before display. A material validated update may automatically publish a
new composite release through the backend workflow, but it does not switch the
current page or change an existing research interaction; the existing view
remains pinned until explicit refresh or reopen.

Active serving and validated review are distinct:

- active serving is published and must not be labeled unpublished review;
- validated Fund review is offered only when its snapshot or manifest differs
  from active serving, is used only after explicit user selection, and remains
  labeled not published; identical bytes are not a distinct review candidate;
- a binding mismatch is an error, never an invitation to merge old and new
  response state.

## China Public Fund Page

The current Fund workflow preserves the accepted financial object model:

```text
Fund product
-> Fund share class
-> Tradable instrument
-> Exchange listing
-> canonical Series
```

Name/code search returns accepted typed matches with effective intervals.
Codes and names remain aliases, not durable identity. The page exposes relevant
relationships, lifecycle-effective aliases, observation coverage, metric/unit/
currency context, source family and provenance references, and clear data-state
meaning. Observation coverage is not legal or economic lifecycle.

The ordinary entry is the Fund product. Reveal a share class when NAV, fee or
subscription/redemption meaning requires it, and a listing for exchange-traded
price/volume/amount. Tradable-instrument identity normally stays in the backend
or Advanced view. Listing or share-class termination does not by itself end the
Fund product; conversion and manager transfer require real-world continuity
evidence, not an inferred merge or split.

Series queries require a selected typed object, supported metric, explicit
start/end, and a backend-enforced per-request bound. The current backend default
is 1,000 and maximum is 50,000 rows per request; these are execution-safety
limits, not limits on the financial history a user may select. The ordinary
user selects a financial period, not an API row limit. The result summary
retains the metric context of the current returned result. CSV export contains
only that returned result, but carries its existing typed subject/external-code,
metric/Series,
financial-time/unit/scale, release/snapshot, and safe provenance context so the
artifact remains independently identifiable outside the browser.

The populated Fund workspace must remain within the document at desktop,
tablet, and mobile widths. Grid and flex descendants propagate shrinkable width
ownership; long identifiers and relationship metadata wrap within their owning
panel; charts size to their content owner. A wide result table may preserve its
minimum readable width only inside a bounded horizontal scrolling region. It
must not impose that intrinsic width on the page.

## China Equity Page

`China Equity` is a regional product scope, not a Universe. User-facing scope
distinguishes `Mainland China Equities` from `Hong Kong Equities`; A-share,
B-share, and H-share appear only as actual security/share classifications.
The existing page's structured resolver still accepts:

- exchange `SSE`, `SZSE`, `BSE`, or `HKEX`;
- numeric code;
- alias-effective date used only to select the lifecycle-effective code episode.

The alias-effective date is not the market observation date. A successful
resolution displays durable listing, instrument, and entity identities plus the
listing interval, lifecycle status, board, share type, and issuer display name.
The backend also exposes release-bound `/api/equity/china/search` for ordinary
name/code/alias discovery without a preselected exchange. It returns accepted
listing matches with venue and lifecycle context; the user selects one
before the existing listing-ID query path continues. The current page is not
implicitly redesigned by that backend contract correction.

Current Series are explicit `unadjusted` daily data for `equity.open`,
`equity.high`, `equity.low`, `equity.close`, `market.volume`,
`market.trade_amount`, and `market.turnover_rate`. A single current API request
requires a listing, metric, ordered start/end dates with at most 366 days
between endpoints,
and a 1-to-5,000-row bound. Those are technical single-request limits, not the
user's allowed financial-history range. A valid longer selection within proved
available bounds remains a product request; the application must fulfill it
through safe bounded execution without prescribing one mechanism here. This
does not claim that the current UI already implements long-range orchestration.
Results show Series identity, unit, currency, scale, financial-time role, and
safe source-observation references.

Raw/unadjusted price remains a direct market fact. Future governed adjusted
price and total-return Series must be labelled separately with their method,
anchor, input and reinvestment meaning; provider qfq/hfq labels are not FR
methodology. This is presentation semantics, not implementation authorization.

Ordinary retrieval offers common period presets and a custom range constrained
by the selected object pool's proved available bounds. In a multi-object view,
the earliest available object may set the overall start; later-starting objects
simply have no observations before their own start. Avoid creating user-facing
error states for dates the UI can prevent users from selecting. Internal
request windows and row/page bounds do not shorten the selectable financial
history; they govern how a valid selection is executed.

Lifecycle browsing is `Current | Historical | All`, default `Current` once
release-bound classification is proved. Direct accepted code/name/alias search
spans all accepted lifecycle states, including Historical. Accepted Unconfirmed
identities remain searchable and visible under All, with optional explicit
Advanced/Explorer filtering; discovery candidates never enter formal results.

Every chart label preserves observation identity: a displayed date and value
must come from the same returned row. First and last observations are not paired
with interval extrema; minimum and maximum labels carry the dates of the rows
that produced those extrema. Sampling for drawing must retain the first, last,
minimum, and maximum rows.

## Catalog And Availability

The `/data` page is the Data-area landing for object discovery and available
Fund/Equity research, not a generic table catalog or update console. It may
show current Fund/Equity scope, supported interaction, and known gaps; detailed
operation status belongs under Settings. It must not invent product counts,
external-Universe denominators, record totals, freshness, coverage ranges, or
fields that current serving APIs do not establish. Release and database
identifiers belong in secondary diagnostics.

Future richer catalog, field-definition, coverage, or discovery pages require
separately accepted backend contracts. Older catalog presentation primitives may
be reused, but old local-workspace aggregation does not become current financial
truth merely because presentation code exists.

## Updates And Errors

The ordinary Settings > Data Update action sends one configured Update intent to
`POST /api/data-console/update`. Backend current configuration freezes the
required financial Update Scope denominator; the browser supplies no work
packages, source routes, or financial semantics. Mainland and Hong Kong Equity
may have distinct backend owners without becoming separate Universes or top-level
product domains. The UI displays each scope's check result and data-check date,
separate from current serving availability. A material validated update may
publish Fund or Equity component changes automatically; an existing pinned
research view stays unchanged until deliberate refresh or reopen.

An independently checkable update scope may be narrower than a Fund or Equity
publication component. The current configured action is not a permanent limit
on future market/data-family check granularity. Future
regional scopes remain within their financial Universe, and provider/API routes
are not automatically ordinary user-visible scopes. Show the configured,
supported required scope and its outcome; a failed required route must not
silently disappear from that run's denominator.

An independent Fund/Equity component failure leaves its prior validated data
usable while a successful component may advance in a new composite, provided
shared release integrity is proved. Market-level partial advancement, such as
Mainland Equity T1 with Hong Kong Equity T0, is accepted Stage B behavior when
the successful scope, inherited failed scope and shared Equity successor are
proved safe. Show each selected scope's last successful check and the
failed scope's actionable reason; never present an all-green installation-wide
freshness date after partial failure. A shared/core integrity failure is a
release-safety stop, not a local stale-data warning. Translate backend
operation machinery into simple user outcomes and keep details secondary.

The lifecycle read model's aggregate Equity component `queryable` fact does
not prove serving availability for Mainland or Hong Kong individually. A
scope's `last_checked` date proves its check history, not current market
serving availability. Until the backend supplies explicit market-level serving
evidence, Data Status and Data Update must leave each Equity market's current
availability unconfirmed when the shared component is queryable. They may
show a negative availability conclusion when the shared component is
unqueryable. Do not turn a failed or disabled market's check history into a
claim that its prior data remains in use.

The ordinary user-facing freshness concept is per-scope `数据核查日期` (data check
date): the calendar date on which FR last successfully completed all required
checks for that configured, supported update scope. A complete successful
`no_material_change` check may advance it without publication; an incomplete
or failed required check may not. Stage B now provides durable required-scope
completion evidence through the lifecycle read model; show unavailable when it
is `not_proven` rather than infer a date from an operation timestamp. This date
is not the latest market/NAV observation, report period, disclosure or
lifecycle-effective date, component publication time, or release creation
time. Separately proved coverage-through dates belong to the relevant source
or data family, not a competing ordinary database-wide freshness label.

Ordinary read/search/query work and user-triggered updates use distinct busy
state. A read may disable its own control, but it must not make an update control
appear to be running. A service/request outage is described as service
unavailability and must not be rewritten as a release capability conclusion.

Normal errors show a safe user message and, when supplied, error code, request
ID, and operation ID. They do not expose credentials, raw payloads, local paths,
provider parameters, SQL, tracebacks, stdout/stderr, or recovery internals.
Ordinary explanations follow the selected product language. Stable FR error
codes are the first localization key and structured error classes are the
fallback. Chinese presentation does not require raw English server wording;
unknown semantics are identified as not safely localizable rather than assigned
invented financial meaning. Diagnostic identifiers remain language-neutral.

The durable backend lifecycle readback at
`/api/data-console/operation-lifecycle` is the frontend authority for current
composite serving state, per-Universe component availability, recent
First-Install/Fund/China Equity operation outcomes, publication relationship,
retry/recovery eligibility, and a monotone freshness revision. The frontend
does not infer these states from leases, PIDs, runtime paths, checkpoints,
CAS records, or raw exceptions. A Fund or Equity operation may advance only
its own component inside a new composite release; lifecycle UI must not label
that result as an installation-wide refresh. Existing research bindings remain
immutable while a newer release becomes available.

The installation's current data-selection authority is a separate read at
`/api/data-console/data-configuration`. It reports the explicit current
configuration, its enabled Universes, and an unset/no-enabled state. Frontend
code must not union retained Desired Data Profile rows or infer future update
selection from serving data. A disabled Universe may retain previously
published serving data; configuration and serving lifecycle remain separate.

## Local And Review Tools

Morningstar credential management is a standalone local panel reachable through
the supported FR gateway by explicit local access only. It is not ordinary
navigation or V1 serving authority and must never echo a credential into the
ordinary shell.

Parse Lab remains a separate local review application under the protected
separate Parse Lab installation, with its own React review UI and API. FR
communicates with it through an HTTP-only client and exposes bounded financial-
report parse registry/queue/decision bridge APIs. Its independent UI is outside
the FR ordinary product shell and is not Fund + China Equity V1 serving
authority. This stage neither redesigns nor republishes Parse Lab.

## Research Product Integration Boundary

Research1 is the first accepted backend research capability. Its frontend
integration belongs inside `Research > Statistics` and consumes the
release-pinned comparative-Series application contract rather than exposing
Fund or Equity as permanent top-level research apps. The page-level contract
must preserve the receipt's release identity, resolved durable Series bindings,
exact common-date intersection and missingness states, explicit NAV/
accumulated-NAV/unadjusted-price semantics, calculation labels, self-
identifying exports, structured errors, and execution-time re-queryability
disclosure.

This document records the product boundary only. It does not claim a general
descriptive-statistics engine, saved Research Artifact store, historical-
release reopening, PIT, portfolio, factor, backtest, or simulation exists.
The current comparative calculation is one Statistics capability, not the
ordinary product name. A Data result cannot claim same-version handoff into
Statistics because the current Research entry requeries the active release.

## Security And Performance

- Parameterized current APIs only; no arbitrary SQL from the browser.
- Server-owned metric, identity, date, adjustment, and row-limit validation.
- Internally bounded request windows and row/page limits; no wildcard-all or
  unbounded historical scan initiated by an ordinary page. These safety bounds
  are not the user's financial-history selection limit.
- Safe escaping for user/backend text and no remote third-party JavaScript.
- A service or secondary capability failure is displayed without converting
  stale cached state into success or preventing unrelated shell navigation.

## Acceptance Gate

Implementation-level static/API contract tests establish code integrity only.
Independent acceptance must exercise the supported launcher in a real browser
and record ordinary Fund and Equity workflows, active/review labeling, release
pinning, update outcomes without unauthorized provider/data effects, failure
states, source/time meaning, export, navigation history/deep links, bilingual
text, keyboard/focus behavior, readable contrast, reduced motion, and desktop/
tablet/mobile layouts. It must also prove obsolete pages/modules are unavailable
through the supported gateway and local/review tools retain their separate role.

API, data-foundation, static DOM, JavaScript syntax, or Review ZIP validation
alone does not establish current UI usability.
