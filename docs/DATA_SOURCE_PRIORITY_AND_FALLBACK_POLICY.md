# Data Source Priority And Fallback Policy

Routing status: `active_source_governance`
Authority: routed by `AGENTS.md`; cannot override `FR_CURRENT_STATE.md` or `FR_NEXT_TASK.md`.
Current truth route: `AGENTS.md` -> `docs/FR_CANONICAL_CONTEXT_INDEX.md` -> `docs/FR_CURRENT_STATE.md` -> `docs/FR_NEXT_TASK.md`.


## Source Scope And Eligibility

FR builds every Universe toward full available-data coverage. Mainland China
Equity, Hong Kong Equity, and China Public Fund work are phased priorities only.
A-share, H-share, and ETF remain valid when they identify the actual security
classification or source route. AKShare is an acquisition adapter where its
actual upstream, financial semantics, coverage and observed interface health
make it suitable; it is neither an automatic first choice nor final provenance.
Preserve the actual upstream source in lineage.

For an existing domain, first consume the accepted source-intelligence evidence
routed by `FR_CANONICAL_CONTEXT_INDEX.md`. Compare field/schema, identity,
unit/date role, historical coverage, observed successes/failures and known
fallbacks before external discovery. Recheck when that evidence is absent,
stale, currently unhealthy, semantically insufficient or a materially better
authoritative/stable route is available.

Prefer a suitable official institution, exchange, publisher, regulator,
central bank or statistical agency route, or another public/free route already
proven stable by FR. Other stable public routes with clear provenance remain
eligible. Eastmoney-backed endpoints, including AKShare wrappers with Eastmoney
upstream, are fallback candidates when stronger routes are unavailable,
materially incomplete or fail bounded current checks. Evaluate health per
interface and period: one Eastmoney failure does not invalidate every endpoint.
Record the actual upstream, observed route health and reason for fallback;
do not silently promote an adapter name into economic-source authority.

Paid, token-gated, credentialed, login-only, commercial-terminal, and licensed
vendor sources are excluded by default. They may be evaluated or called only
after explicit user approval. Official institutions and authoritative public
third-party sources are usable by default when retrieval, semantics, identity,
and minimal QA succeed.

Official, issuer, regulator, exchange, filing, and other authoritative public
real-world evidence is not merely a fallback after local source failure. Use it
proactively when local rows, provider labels, names, codes, or route behavior do
not prove economic identity, lifecycle boundaries, event meaning, source
semantics, or date roles.

---

Generated: 2026-05-23T10:05:16Z

FR keeps FRED, SEC, BaoStock, Tencent, Sina, THS, CNINFO and Eastmoney by data domain. It does not collapse onto AKShare or any other universal source.

Fallback sources are used when primary values are unavailable. Fallback values do not silently overwrite primary values and always retain source provenance.

Source availability is not lifecycle evidence. First/last observation dates,
provider coverage windows, and source gaps describe the source interface and FR
coverage; they do not establish listing, delisting, report, revision, or
economic-series start/end events without authoritative event evidence.

## Open-World Semantic Evidence Escalation

When local rows, contracts, code, and financial identities do not establish an
exact field meaning, apply **Open-World Evidence Escalation（开放世界证据升级方法）**.
Search issuer/product-owner/index-publisher evidence first, then exchange,
regulator, government or standard-setter evidence, then original provider
documentation or a public data page. Other authoritative public sources may
follow; reputable third parties only corroborate. Record direct pages or public
document identifiers, not search snippets.

Search for counter-evidence and test x1, common scale transforms, neighboring
observations, and appropriate financial identities. A source match is scoped to
the tested entity, interface, field, date or report period, statement/series,
unit, currency, scale, and version. Do not infer a provider-wide historical rule
from one match. If evidence remains insufficient, name the next exact public
document, period retrieval, numeric fingerprint, cross-source sequence, or
bounded alternate-source path instead of treating a diagnostic label as a
terminal outcome.

## 2026-06-15 AKShare And Source Expansion Rule

AKShare may be used for China-market public data when it provides the needed
field, date, definition and stable connector behavior under the upstream-aware
priority above. AKShare is not the only access route or final provenance.

AKShare is recorded as the acquisition adapter. The actual upstream provider is
recorded separately whenever recoverable, including Eastmoney, Sina, Tencent,
an exchange, index publisher, regulator, central bank, statistical authority,
ChinaMoney, NBS, PBOC, or another named public source. A wrapped route with an
unknown upstream remains uncertain and must name the next executable
investigation route rather than treating AKShare itself as the economic source.

When AKShare coverage, field exposure, source dates, definitions, or
connector stability are insufficient, FR must name source candidates and the
license/authorization risk. For A-share capital-flow work, named candidates
include SSE, SZSE, CSF, HKEX Stock Connect pages, SAFE, CNINFO, Eastmoney,
THS/iWencai where authorized, fund companies, Baidu Index, Xueqiu, Weibo,
broker/research feeds, Tushare/GM, Wind/Choice/Bloomberg, and official
exchange/regulator sources. Entitled or licensed commercial candidates remain
disabled until the user explicitly approves their use.

Do not record "AKShare unavailable" as a terminal blocker without a named
source-expansion action.

Planned source-rebuild waves are: authoritative subject and series registry and
source catalog; official Macro and Interest Rate sources; Equity, Index and
Derivatives market data; Fund sources (including genuine ETF-specific routes)
and Morningstar; financial statements and fundamentals; Fixed Income, Foreign
Exchange, Commodity and remaining domains; then full-database
reconciliation, deletion and cutover. Every unresolved item remains in the
carry-forward registry until explicit final disposition.

## 2026-06-16 Derived Data And Source Gap Rule

Do not record "source does not directly provide a label, return, drawdown,
rolling beta, frequency rollup, or relative outperformance" as a terminal
source gap when the needed source-traced base fields exist. Derived variables
may be high-confidence if the input source trace, formula version, time
boundary, no-lookahead rule, and latest/history information-availability readiness
semantics are recorded.

Keep this separate from true source gaps. True ETF net flow, broader foreign
capital, stable theme taxonomy/history, stable breadth history, LHB true
identity, attention-as-flow, and latest-only-as-history cannot be created by
generic derivation or proxy wording.

`FR_A_SHARE_CAPITAL_FLOW_MVP_UNRESOLVED_ISSUE_RESOLUTION_V1.md` is a
historical example of this rule: derived labels and rollups are executable from
registered structured data, while true-flow and forbidden-claim boundaries are
preserved.

`FR_A_SHARE_CAPITAL_FLOW_MVP_FULL_EXECUTION_SPRINT_V1.md` is a historical
execution example. It materializes full daily rollups, labels, features,
breadth/theme proxies, ETF controls, and OOS records from registered
source-traced inputs. It also shows the required fallback behavior:
Sina `outstanding_share` can support bounded free-float-share and
float-market-cap derivation, but it cannot be promoted to total shares or
total market cap; ETF activity controls cannot be promoted to true ETF net
flow; and northbound cannot be promoted to broader foreign capital.

`FR_A_SHARE_CAPITAL_FLOW_MVP_FULL_EXECUTION_SPRINT_V2.md` is a historical
source-expansion example. It shows that read-only production-candidate targets
may be used as registered structured inputs, but latest-only ETF share data
cannot become history, ETF activity cannot become estimated or true ETF net
flow without historical share-change plus NAV plus corporate-action controls,
and board-prefix or northbound proxies cannot become real theme taxonomy or
broader foreign capital.

`FR_NON_AKSHARE_SOURCE_AND_REPORT_PIPELINE_V1.md` is a historical non-AKShare
source/input example. It records direct Eastmoney/Sina, official
SSE/SZSE/CNINFO/HKEX/SAFE/CSF, fund company, THS/iWencai, Tushare Pro, and
licensed vendor paths separately. A single endpoint-family failure must not
be generalized to provider failure, and metadata queues must not be promoted
to parsed financial statements or accepted observations.
