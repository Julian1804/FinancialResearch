# FinancialResearch

FinancialResearch is a comprehensive financial research platform. It is not only a financial-report parser, not only a fund-flow tool, and not a single-source market-data dashboard.

The platform collects, governs, and connects multi-source financial data so that research workflows can produce statistical reports, human-in-the-loop GPT Web analysis packets, structured reports, forecasts, backtests, revision records, and decision-support evidence.

## Current Research Mainline

The current mainline is **global and China capital-flow research**:

- Where does money come from?
- Which countries, asset classes, sectors, currencies, funds, ETFs, companies, and markets receive or lose capital?
- How can price movement be separated from actual or proxy capital flow?
- How do global flows affect China assets, A-shares, H-shares, sectors, and companies?
- How should later data validate, falsify, or revise earlier forecasts?

This is the current research focus, not the permanent only topic. The platform remains designed to add other research themes.

## Platform Modules

- **Data Sources**: FRED, SEC, BaoStock, Tencent, AKShare interface-level wrappers, CNINFO, Eastmoney, Sina, THS, Morningstar, World Bank, Treasury, BLS, and future official or licensed sources.
- **Data Products**: field-level trusted candidate previews, Morningstar candidate data products, macro/asset/commodity historical products, and future production candidates.
- **Research Workspace**: research object, topic, data category, time window, as-of snapshot, and statistical report generation.
- **Report Workflow**: copy-to-GPT prompt, human-in-the-loop GPT Web discussion, final report upload, report classification, and structured storage.
- **Forecast / Backtest / Revision**: testable forecasts, actual lookup, backtest results, revision candidates, and research workspace index.
- **Dashboard / Manual Updates**: Dashboard v1, Morningstar manual token workflow, source status, data product refresh hook, and operational panels.
- **Storage / QA / Governance**: NAS-first storage, retention policy, QA summaries, provenance, candidate promotion, and trusted consumption boundaries.

## Current Status

- Morningstar is `ready_for_operational_manual_updates`: token is provided manually, no auto-login, no password storage, no token leakage, full backfill disabled unless explicitly planned.
- A-share multi-source policy is established: Tencent daily via AKShare is the current primary candidate, BaoStock remains a validation/historical partner, Eastmoney daily is deferred, and Eastmoney/Sina/THS financial interfaces are handled by interface-level policy.
- Storage retention policy is established: keep consumption-grade structured data, manifests, QA and provenance; retain raw/intermediate artifacts short-term unless audit requires otherwise; generate cleanup plans only.
- Dashboard manual update framework is established and keeps formal trusted consumption off by default.
- Field-level trusted candidate preview exists for A-share/ETF OHLC, while limited fields remain blocked from trusted preview.

## How To Start

Backend:

```powershell
D:\workspace\envs\financial_research_backend\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8030
```

Dashboard action server:

```powershell
cd D:\workspace\FinancialResearch
D:\workspace\envs\financial_research_backend\Scripts\python.exe scripts\run_dashboard_v1_action_server.py --host 127.0.0.1 --port 5188
```

Dashboard URL:

```text
http://127.0.0.1:5188/
```

Parse Lab is a separate service and is not part of this repository. FinancialResearch calls it through HTTP only when parser workflows require it.

## Documentation Map

Project-level:

- [Project Context](docs/PROJECT_CONTEXT.md)
- [Current Research Mainline](docs/CURRENT_RESEARCH_MAINLINE.md)
- [Project Roadmap](docs/PROJECT_ROADMAP.md)
- [Architecture Overview](docs/ARCHITECTURE_OVERVIEW.md)

Research topics:

- [Global and China Capital Flow Mainline](docs/research_topics/capital_flow/GLOBAL_AND_CHINA_CAPITAL_FLOW_MAINLINE.md)
- [Capital Flow Research Framework](docs/research_topics/capital_flow/CAPITAL_FLOW_RESEARCH_FRAMEWORK.md)
- [Flow Proxy and Exposure Methodology](docs/research_topics/capital_flow/FLOW_PROXY_AND_EXPOSURE_METHODOLOGY.md)

Data sources:

- [Data Source Strategy Overview](docs/data_sources/DATA_SOURCE_STRATEGY_OVERVIEW.md)
- [Morningstar Pipeline Status](docs/data_sources/MORNINGSTAR_PIPELINE_STATUS.md)
- [A-share Multi-source Policy](docs/data_sources/A_SHARE_MULTI_SOURCE_POLICY.md)
- [Macro Data Source Plan](docs/data_sources/MACRO_DATA_SOURCE_PLAN.md)
- [Commodity and Asset Data Plan](docs/data_sources/COMMODITY_AND_ASSET_DATA_PLAN.md)

Modules:

- [Macro Module Framework](docs/modules/MACRO_MODULE_FRAMEWORK.md)
- [Asset Class Module Framework](docs/modules/ASSET_CLASS_MODULE_FRAMEWORK.md)
- [Commodity Module Framework](docs/modules/COMMODITY_MODULE_FRAMEWORK.md)
- [A+H Stock Module Framework](docs/modules/AH_STOCK_MODULE_FRAMEWORK.md)
- [Sentiment/Event Module Framework](docs/modules/SENTIMENT_EVENT_MODULE_FRAMEWORK.md)
- [Report Workflow Module Framework](docs/modules/REPORT_WORKFLOW_MODULE_FRAMEWORK.md)
- [Forecast/Backtest Module Framework](docs/modules/FORECAST_BACKTEST_MODULE_FRAMEWORK.md)

Governance:

- [Storage Retention Policy](docs/storage/STORAGE_RETENTION_POLICY.md)
- [Dashboard Information Architecture](docs/dashboard/DASHBOARD_INFORMATION_ARCHITECTURE.md)
- [Agent Workflow and Safety Rules](docs/development/AGENT_WORKFLOW_AND_SAFETY_RULES.md)

Detailed historical reports are preserved under `docs/` and should be read from their module-specific files instead of being compressed into this README.

## Safety Boundaries

- Never commit `config/local_secrets.json` or any token.
- Never print full API tokens in docs, logs, runtime JSON, or stdout.
- Formal trusted consumption is off by default.
- Morningstar does not auto-login and does not store passwords.
- Non-China equity time series are not collected by default; non-China equities may be represented as entity shells or exposure constituents only unless a specific approved data product says otherwise.
- Do not delete, move, or rename NAS large directories.
- Do not run `git init`.
- Git commands must be scoped to `git -C D:\workspace\FinancialResearch ...`.
