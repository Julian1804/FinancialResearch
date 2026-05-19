# A-share Daily Multi-source Strategy

## Current Strategy

1. Baostock: `operational_source`, `candidate_external_data`, current primary fallback.
2. AKShare: `priority_repair_source`, optional when unstable; if repaired, use as secondary source.
3. Eastmoney direct: `deferred_secondary_validation_source`; can become secondary only when client/network stabilizes.
4. Future official/authorized sources: exchange official feeds, authorized Eastmoney, Wind, Tonghuashun, Morningstar, or similar licensed sources.

## AKShare Repair Outcome

- repair status: partially_repaired
- root cause: Eastmoney push2his network/TLS/upstream disconnect affects AKShare and direct clients; failure occurs before JSON parse and is not fixed by headers, trust_env=False, curl, HTTP/1.1/TLS1.2, or curl_cffi in this environment.
- Eastmoney-backed path: not available
- alternative AKShare daily path: available

## Trust Rule

Baostock, AKShare, and Eastmoney direct remain candidate external data. Cross-source agreement can enter consumption-grade staging candidate, but not formal trusted consumption.
