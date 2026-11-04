# FR Backend Engineering Contract

Routing status: `active_backend_contract`
Authority: minimum application/backend coding contract beneath `AGENTS.md` and
the canonical current-state route.
Updated: `2026-10-28`

For the accepted Stage A Data Product projection, reuse the existing financial
query owners. A user-safe logical catalog is distinct from physical manifest
members; it must declare presence, count confidence, preview/export
capability, and dictionary version separately. Do not infer lifecycle Current
from absence of an end date, or turn a source-observation key into a provider
name. A multi-field projection may union returned dates only after selecting
one durable object and one Series per metric; a failed field is not a missing
observation. Stage A acceptance does not change the accepted Fund/Equity
identity architecture or authorize Stage B implementation.

This contract protects the diagnosability and ownership of ordinary FR backend
behavior. It does not redefine financial, identity, data, update, release,
retention, or recovery semantics.

## Financial Identity, Lifecycle, And Component Boundaries

Provider rows and discovery candidates are evidence, not accepted identity or
formal population. A material unresolved candidate can leave its selected
component Update incomplete while its prior validated component remains
usable. Accepted identities and lifecycle classes are decided from appropriate
real-world evidence and sealed into an immutable release. The normalized
Current/Historical/Unconfirmed projection is release-bound; an old release
cannot be reclassified by today's website. Historical may have a null exact
`effective_end` where cessation is proved but its day is not. Episode/fact
attribution is a separate decision and may require a tighter boundary.

Independent successful Fund or Equity component Updates may publish a new
composite carrying forward an unrelated failed component. The result must
identify per-component success/failure and last successful update, never an
all-green installation-wide date after partial failure. A shared identity,
subject-graph, manifest, coverage, database-generation, query-contract or CAS
integrity failure stops publication where safe successor closure cannot be
proved. A local provider failure does not by itself invalidate another
independently validated scope or component. This does not weaken single-writer
ownership or immutable rollback.

## Update/Check Scope And Failure Aggregation

An independently checkable scope is a configured, supported financial/data-
family obligation whose required source checks and outcome can be proved. It
may be narrower than a publication component: Equity × Mainland China,
Equity × Hong Kong, or a future regional Equity scope may each own applicable
families without becoming a new Universe. Fund, Fixed Income, Macro and FX
use their own financially meaningful scope dimensions; no universal
country-to-venue hierarchy or permanent schema tuple is implied. Current
Fund/China Equity entry points and persisted `CN_PUBLIC_FUND`/`CN_A_SHARE`
component IDs are V1 implementation/compatibility boundaries, not a limit on
future check granularity.

Resolve the required denominator for a run from current-effective user
configuration and supported source/data-family contracts before execution.
Preserve each required scope in the result when a route fails; neither provider
availability nor fact presence removes it. Do not add unselected or unsupported
markets/families merely because a broader Universe is enabled. Aggregate
provider/route results by their source role into required-source-contract,
update/check-scope, publication-component and composite-release outcomes.
An optional candidate route may fail with an explicit warning; failure of a
required authoritative route leaves its scope incomplete. A provider failure
does not automatically fail a market, Universe or whole database.

Current Fund/Equity component-level partial publication remains supported.
The accepted architectural direction also permits Mainland Equity T1 with
Hong Kong Equity T0 inside a new immutable Equity successor only when the
successful market's checks and accepted changes are proved, the inherited
failed-market state remains valid, and shared Equity/release integrity passes.
The integrated Stage B candidate implements this market-level workflow and
its completion proof; independent Planner acceptance is pending. Its failed-
market inheritance is conditional on shared successor and release integrity,
not a permission to omit a failed configured scope from the run result.
Execution scope, inherited financial state, publication component and
composite release must not be treated as the same granularity.

`数据核查日期` (data check date) is the date FR last successfully completed the
required checks for that exact update scope. A complete successful
`no_material_change` check may advance it without a new publication; a failed
or incomplete required check may not. The check receipt must prove scope and
completion. Operation completion time alone, component publication time,
market/NAV observation date, report period, disclosure date and lifecycle
effective date do not prove this date. Coverage-through information, when
supported by a source contract, remains scoped source/data coverage, not a
second ordinary database-wide freshness label.

Governed, frequently reused derived financial Series may enter standard facts
only with stable metric/subject/Series meaning, formula, input and revision
identity, units, currency, time roles, lineage and reproducible methodology.
Adjusted price and total return are different economic Series; a provider
adjustment label is not FR methodology. One-off model features and forecasts
remain Research Artifacts. This is an admission contract, not authorization to
produce those Series in the current task.

## Application/Product Layer

The Application/Product Layer is the stable boundary between researcher-
oriented frontend workflows and maintainable financial domain/capability
services. It may coordinate several existing owners for one workflow, produce
presentation-oriented projections, enforce application policy, deduplicate
equivalent work within one action, coalesce or batch compatible requests,
request only required fields/ranges, reuse bounded request/session results, and
expose stable product APIs.

It must not own canonical financial truth, reinterpret Universe-specific
semantics, allocate economic identities, become a universal financial object
model, persist a second authoritative fact database, or hide a structural
full-history scan behind a cache. Physical grouped reads, indexes, partitions,
and serving artifacts remain the responsibility of their domain/serving/storage
owners. An application optimization may reduce unnecessary work but cannot
substitute for a correct physical access path.

Application APIs should support researcher journeys such as discovery/check,
governed update when needed, verification, tool/input selection, execution,
inspection, adjustment, rerun, save, resume, and export. They do not force
frontend navigation to mirror backend modules, tables, manifests, or service
boundaries.

1. Register every reachable router in `backend.app.composition` with one honest
   role: V1 serving, V1 update, local operational, or review tooling.
2. Routers own transport. Financial semantics, identity resolution, physical
   reads/writes, and update orchestration belong to production backend owners.
3. Pin serving context before financial resolution or data access. Emit the
   safe release, snapshot, database-generation, capability, and stage context
   when it is known.
4. Give every request a correlation ID and every mutation an operation/run ID
   before meaningful work. Carry the same operation ID into its exact result or
   failure evidence.
5. Preserve specific financial/domain error codes. Add the shared application
   error class for diagnosis; do not replace useful domain meaning or silently
   translate an unknown failure into a business conclusion.
6. Production backend modules must not import task scripts as implementation
   owners. A retained CLI or historical module may import a production owner as
   a compatibility wrapper.
7. Declare startup dependencies and configuration at their actual owner. One
   setting has one environment-variable contract; partial route-prefix or
   historical-path overrides are invalid.
8. Historical or compatibility paths may remain for evidence, recovery, or
   tests, but they must never select ordinary serving/update state implicitly.
   Owner moves require service/HTTP parity tests, not source-text assertions.
9. Put genuinely shared technical infrastructure under a neutral owner. Do not
   make a new Universe import another Universe's business module, and do not
   generalize Universe-specific financial semantics into a universal framework.
10. Ordinary reads are side-effect free. Schema creation, index rebuilding,
    cache publication, and directory creation belong to explicit write or
    initialization paths.
11. A known failed or busy mutation uses a deliberate non-2xx transport status
    while preserving its domain result, operation ID, and error class.
12. Current product tests live under `tests/`; task and historical tests under
    `scripts/` are not the implicit current suite. Public source selection must
    compute and validate the active application import closure. Tests that
    resolve installation storage run under explicit disposable local/NAS and
    bootstrap roots; a test runner must fail closed before resolving a default
    production control path.
13. Preserve the data-production boundary: a deterministic platform-produced
    metric may enter standard facts only through an explicit financial meaning,
    input, identity, unit/currency/scale, lineage, and timing contract.

## Modeling Stage 1 Backend Boundary

The Stage 1 Modeling backend is a release-bound read/compute capability. A
Preview freezes the selected subject/Series bindings, release identity,
information-time cutoff, transformations, target/horizon alignment, missing
policy, and chronological train/validation/test partitions. Run accepts only
the unchanged Preview candidate digest; it never silently rebinds to a newer
active release. Training-derived preprocessing and label thresholds are fitted
inside the training boundary, and an unproved availability time cannot satisfy
an explicit knowledge cutoff.

The Dataset Builder is a temporary Research Artifact boundary supporting
supervised, univariate and multivariate time-series, and entity/time panel
inputs. For release-bound Equity panels, the modeling owner accepts only a
bounded `Equity:Listings:<listing-id>|<listing-id>:<metric>` selection and
resolves each durable listing ID through the pinned accepted identity owner to
its durable `entity_id`; it never creates a second identity layer or derives
panel identity from provider codes. All panel variables must bind the same
entity set. It does not create standard facts or a universal financial schema.
Model adapters own model-specific parameters and diagnostics. Comparison and
bounded optimization are one Modeling task and use the same installation-wide
execution slot; optimization never consumes the held-out test partition.

Model execution is not database publication and never holds the database writer
lease. Frozen inputs and truthful run state are persisted under the Modeling
runtime owner so browser closure does not cancel a task. A Preview candidate
is single claim: one durable run owns its digest and a duplicate Run is
rejected. A queued cancellation releases the Modeling slot; a running task
uses a separate compute process so cancellation can terminate its owner,
discard the result and release the slot without waiting for fitting to finish.
A service restart marks a dead-owner active run interrupted; restart recomputes
from the frozen input rather than querying a newer release. Completed unsaved results follow
the approximately 24-hour runtime retention policy and may be reclaimed under
storage pressure. User exports are explicit artifacts outside that cache
lifecycle. No permanent model-result database is introduced.
Ordinary Modeling run discovery projects a bounded recent summary from the
existing temporary run files; single-run read remains the detail authority.
The browser download identifies a completed run and uses the accepted typed
export content. The server chooses the temporary export location and filename;
the client supplies no filesystem destination and receives no local path.
    Research/model outputs and saved runs remain Research Artifacts, while read
    models remain rebuildable projections; neither is silently promoted by
    persistence or query reuse.

Model names must match statistical output. Fixed Effects enables entity or
time effects explicitly. Held-out values for known entities include their
fitted entity effects; future date effects are fit-only because their values
are unobserved. GLS requires an explicit finite positive-definite
training-row covariance matrix. Volatility adapters expose conditional
variance and volatility, not a raw-level return forecast or raw-level RMSE.
Markov regression/autoregression expose fitted regime state and probabilities
without claiming an out-of-sample model forecast. Panel missing-row filtering
keeps durable entity IDs aligned; sequential transforms and fills stay within
one entity; chronological partitions contain whole economic-time blocks.
14. Treat ephemeral runtime work as bounded, governed workspace rather than a
    financial layer. Use one configured root and explicit workspace classes;
    bind temporary state to owner/run, expiry, size, lease/pin, and cleanup
    status. Ordinary reads never create uncontrolled persistent directories,
    schemas, databases, or caches.
15. Any application cache key must include immutable release/data identity and
    the complete semantic query specification. Cache hits are not proof that a
    domain or storage owner has removed a structural scan; measure the physical
    path independently.
16. Assign query-efficiency work to the right owner: Application/Product for
    deduplication, compatible batching, projection/range pruning, pagination,
    and bounded reuse; Domain/Serving for locator/grouped/indexed release-bound
    reads; Storage for partitioning, clustering, compaction, and file layout.
17. Do not expose an unimplemented long-term product location as an API or
    capability claim. Stable product locations are Home, Data, Research,
    Settings, and secondary Advanced; Fund and Equity are Data content
    classifications. A new
    frontend integration must consume accepted backend contracts without
    collapsing their distinct financial owners.
18. First-Install and Update Data use the same source adapters and
    identity/lifecycle owners. Initialization from an empty state may publish
    the usable source-discovered subset with explicit gaps; it must not require
    an absolute market denominator, promote provider codes as FR identity, or
    infer termination from a missing observation. Reconciliation failures for
    one object remain traceable without suppressing independently usable rows.

Active names must describe their owner and proven scope: Equity is the asset
class, China Equity a regional capability, and A-share a narrower security
classification. `CN_A_SHARE` and `CN_PUBLIC_FUND` remain persisted component
IDs, not Universe names. New product projections should expose component IDs
and explicit financial scope rather than present these tokens as Universes.
Do not rename a persisted identity/object type, source schema, or release ID
without a separately reviewed compatibility contract. A comparison of two
bindings proves difference, not which one is newer.

For China Equity identity writes, a provider observation proves its own code
and data only; even two-provider agreement is a candidate, not an accepted
economic security or listing episode. HKEX acceptance requires official
current-directory reconciliation against the retained accepted economic and
lifecycle reference. An unknown exact start is permissible only when the
accepted graph uniquely attributes the episode; provider first-price dates
must not fill it. Mainland instrument/listing classification records A-share
or B-share separately from Universe, region, venue and board. SSE, SZSE, and
BSE are peer Mainland venues; a BSE ordinary RMB share is an A-share at venue
BSE, not a third `BSE Equity` classification. Hong Kong Equity uses venue HKEX;
H-share is one classification rather than a market synonym.
Existing UUID/crosswalk keys remain stable when old object-type labels are
projected to accurate current classifications. Crosswalk, locator and Series
scope `jurisdiction=CN`, and older `subject_registry.market` tokens, are
frozen China-region compatibility scopes,
not a universal legal-jurisdiction definition. Current subject projections
state `region=CN`, listing-market `market_jurisdiction=CN` or `HK`, and venue
explicitly; issuer incorporation jurisdiction is not inferred from venue.

Mainland China and Hong Kong financial ingress may use separate market-specific
source, identity/lifecycle, and update owners. Shared neutral identity
infrastructure may be reused, but neither market imports the other's financial
rules merely for orchestration convenience. Both paths converge at accepted
Equity standard-data, serving/publication, and Research contracts. Persisted
names such as `CN_A_SHARE`, active compatibility routes/modules containing
`a_share`, and historical release/schema IDs remain stable interfaces; they do
not assign current taxonomy or force Hong Kong behavior into a Mainland owner.

19. Product lifecycle readback is exposed through the durable
    `/api/data-console/operation-lifecycle` contract. It reports the current
    composite serving release, per-Universe component availability, and recent
    First-Install/Fund/China Equity operation outcomes with a monotone revision.
    It may project accepted writer/recovery facts into `running`, `published`,
    `no_material_change`, `failed`, `busy`, `interrupted_recoverable`, or
    `interrupted_unresolved`, but it must not expose or require frontend
    interpretation of lease rows, PIDs, runtime paths, checkpoints, CAS
    internals, raw exceptions, or physical storage. A component update may
    publish a composite release while carrying forward the other component;
    the lifecycle result must identify the changed component and must never
    imply an installation-wide refresh. Lifecycle reconciliation keeps
    authorities distinct: a user-visible mutating operation must first create
    a durable operation-registration row; failure to establish that anchor
    rejects the operation before lease/provider/publication work. A matching
    active installation writer lease with
    confirmed owner liveness is required to report `running`; runtime markers,
    stage timestamps, and heartbeat fields are diagnostic/recovery evidence
    only. An ambiguous lease remains protected against takeover but is exposed
    as unresolved rather than `running`; the
    committed publication transition and active serving pointer establish
    publication, including after a later operation advances the same component;
    accepted runtime/recovery evidence is consulted only after execution
    ownership ends; and host PID/process liveness is supporting evidence rather
    than operation ownership. A stale First-Install marker is explicit
    interrupted/unknown evidence, even when its host process remains alive. A
    stale `running` row must never override a
    committed publication or a reusable interrupted checkpoint. The lifecycle
    row is a repairable product projection and registration anchor, not a
    financial publication authority; terminal projection failure does not undo
    a committed publication. Stage B must close the remaining status-projection
    gap for a lost response or contradictory terminal operation row; this
    documentation does not claim that gap is implemented away.

Readiness is a bounded serving-contract check. It must prove that the active
Fund and China Equity release bindings and required metadata resolve, without a
provider call, business-data query, rebuild, publication, or historical scan.

Ordinary Fund catalog `active_serving.snapshot_id` and `manifest_sha256` name
the Fund component, not the containing composite snapshot. Its release ID/hash
name the verified composite; a session binds both and rejects stale component
hashes. Equity `/api/equity/china/search` searches only release-bound accepted
episode/identity owners by name, code, or alias. It returns accepted listing
matches with venue and lifecycle context, including genuine ambiguity, and never
promotes a provider alias or chooses an episode for the user.

`/api/data-console/operation-lifecycle` includes `freshness_by_scope` for Fund
and Equity. `last_updated` is the completion time of a recorded publication
whose successor is the currently active component; it is not a market-data
date or `数据核查日期`. Current `last_checked` and Universe-wide
`latest_observation` remain `not_proven` unless a separately authoritative
required-scope check or aggregate observation contract exists. Stage B must
establish durable check-completion authority before presenting a data check
date. Component `availability` means a serving binding is present,
not that every Series has data. Fund/Equity time-series `freshness` reports the
maximum economic time of *returned standard facts* and interval availability
for the selected Series only; an empty bounded result proves no aggregate date.
Neither publication completion nor a Series observation maximum substitutes
for a proved scope-level data check date.

Successor finalization must complete query-visible subject/Series/relationship
metadata from its accepted snapshot-local semantic owner before final manifest
identity, validated-head acceptance and publication. Hash-valid inherited graph
files alone are not semantic completion. Verify query-required attributes and
endpoints, preserve candidate states and unaffected component content, and bind
the proof to immutable owners and graph members. Ordinary queries consume that
release-bound projection; they never repair it from current mutable control.
Metadata corrections create a new successor/release and preserve predecessor
bytes and rollback semantics. Frozen compatibility content is not silently
promoted or re-adjudicated by projection.

## SZSE Listed-Fund Lifecycle Source Contract

SZSE listed-Fund onboarding uses the official structured SZSE ETF, LOF, and
public-REIT catalogs only for current-population discovery, exchange code/name,
and supported product classification. An exchange listing start or termination
date is promotable only from the complete official SZSE Fund notice that states
the effective date. Search results are discovery records rather than facts; the
complete source bytes, official URL, document identity, hash, publication date,
effective-date role, and extracted event are retained together. A bounded
official Fund disclosure may corroborate a missing historical start notice, but
never overrides conflicting exchange evidence.

The resulting episode is bound to the accepted CSRC EID Fund product and share
class before the Fund instrument/listing/Series graph is created. Fund contract
date, first NAV, first/last market observation, provider coverage, code/name,
notice publication date, and current date are prohibited listing-lifecycle
substitutes. Every episode eligible for promotion must be uniquely separable
and non-overlapping: before any later listing start, the earlier episode must
  have an authoritative termination boundary strictly before that start when
  needed to prove unique episode/fact attribution;
every termination must bind to exactly one episode; only the final episode may
remain open. Missing starts, orphan or unassignable terminations, conflicting
dates or types, overlapping boundaries, ambiguous code reuse, or multiple open
episodes remain unresolved for episode/fact promotion. This rule is identical for
current Data Update and historical bootstrap. Current Data Update may resolve
one new current listing on demand; historical bootstrap must discover a bounded
date denominator and fetch complete documents before reconciliation. Neither
route may require a manually curated mapping.

This strict SZSE episode-chain rule does not make an exact end day a universal
prerequisite for classifying a proved ended object Historical. Where a missing
day does not create a real competing-episode attribution or look-ahead risk,
retain the Historical state with null `effective_end`; preserve any observation
whose episode remains ambiguous as source detail rather than guessing its owner.
