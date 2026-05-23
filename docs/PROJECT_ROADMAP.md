# Project Roadmap

## Current Stage

FinancialResearch has moved from parser-oriented prototypes into a multi-source research platform.

The current stage is knowledge consolidation, operational manual updates, data product governance, and project handoff readiness.

## Completed Platform Capabilities

- Dashboard v1 with action server.
- Research Workspace and statistical report generation.
- Human-in-the-loop GPT Web prompt workflow.
- Report upload and classification.
- Forecast/backtest schema and execution.
- Research workspace index.
- FRDataConnectors runtime.
- A-share daily multi-source pipeline.
- Field-level trusted candidate preview for A-share/ETF OHLC.
- Morningstar safe token handling and manual update framework.
- Morningstar capital-flow exposure data product.
- A-share multi-source policy and AKShare interface-level strategy.
- Storage retention policy.

## Near-Term Priorities

1. Continue Morningstar operational manual updates with token-gated, user-triggered runs.
2. Improve capital-flow exposure panels without treating proxy flow as actual flow.
3. Expand structured A-share financial interfaces using source-priority policy.
4. Harden manual update registry stubs for FRED, SEC, BaoStock, Tencent, Sina, THS, CNINFO, and Eastmoney-specific future connectors.
5. Keep field-level trusted preview separate from formal trusted consumption.
6. Build cleanup reports from the storage policy, but do not delete NAS directories.

## Medium-Term Priorities

- Add official/authorized data sources where feasible.
- Improve entity master and identifier crosswalk for funds, ETFs, equities, commodities, and macro series.
- Add H-share/HK data strategy with official or stable sources.
- Add event and policy datasets with source credibility rules.
- Strengthen forecast revision workflow based on backtest results.
- Expand data products only after QA, provenance, and storage boundaries are clear.

## Do Not Prioritize Next

- Do not resume PDF parser optimization as the mainline.
- Do not make manual import the primary data pipeline.
- Do not push Eastmoney daily history into default primary use while unstable.
- Do not treat Morningstar TNA/ENF as consumption-ready while unit scale is unknown.
- Do not open formal trusted consumption as a documentation task.

