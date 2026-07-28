# Data Source Priority And Fallback Policy

Routing status: `active_source_governance`
Authority: routed by `AGENTS.md`; cannot override `FR_CURRENT_STATE.md` or `FR_NEXT_TASK.md`.
Current truth route: `AGENTS.md` -> `docs/FR_CANONICAL_CONTEXT_INDEX.md` -> `docs/FR_CURRENT_STATE.md` -> `docs/FR_NEXT_TASK.md`.


## Source Scope And Eligibility

FR builds every universe toward full available-data coverage. A-share, H-share,
and ETF work are phased priorities only. AKShare is the preferred first access
interface for suitable China-market public data, but it is neither the only
source nor final provenance by itself. When it is insufficient, name a suitable
public free source and preserve the actual upstream source in lineage.

Paid, token-gated, credentialed, login-only, commercial-terminal, and licensed
vendor sources are excluded by default. They may be evaluated or called only
after explicit user approval. Official institutions and authoritative public
third-party sources are usable by default when retrieval, semantics, identity,
and minimal QA succeed.

---

Generated: 2026-05-23T10:05:16Z

FR keeps FRED, SEC, BaoStock, Tencent, Sina, THS, CNINFO and Eastmoney by data domain. It does not collapse onto AKShare or any other universal source.

Fallback sources are used when primary values are unavailable. Fallback values do not silently overwrite primary values and always retain source provenance.

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

AKShare is the preferred first access interface for China-market public data
when it provides the needed field, date, definition, and stable connector
behavior. AKShare is not the only source and is not final provenance by
itself.

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
