# Project Context

FinancialResearch is a comprehensive financial research platform for multi-source financial data, research workflow automation, human-in-the-loop AI analysis, forecast validation, and evidence governance.

## Positioning

FinancialResearch is not a single financial-report parsing tool and not a single fund-flow data collector. It is a research operating system that connects:

- macro data;
- asset-class data;
- commodity data;
- fund, ETF, and capital-pool data;
- A-share and H-share company data;
- filings, announcements, reports, and PDFs;
- news, events, and policy context;
- statistical reports;
- GPT Web manual analysis;
- report ingestion;
- forecasts, backtests, and revisions.

## Current Mainline

The current mainline is global and China capital-flow research. The project is now moving from collecting isolated data blocks into connecting those blocks to support a research question:

> How do global and China-related capital flows move across countries, currencies, asset classes, sectors, funds, ETFs, and companies?

This current mainline does not replace the broader platform scope. Future conversations may add more research themes.

## Data Layer Changes Already Completed

Morningstar:

- manual token input and token status UI;
- manual update framework;
- latest data date scan;
- three-effective-day lookback;
- same-day `latest_collected_wins` upsert;
- snapshot, manifest, QA, failure log, dashboard summary;
- capital-flow exposure data product;
- time-series readiness;
- direction evidence hardening;
- underlying entity enrichment;
- exposure derivation;
- snapshot history;
- non-China stocks as entity shells only, not time series;
- TNA/ENF sidecar blocked by `blocked_unit_scale_unknown`;
- flow proxy remains proxy, not actual flow.

A-share multi-source strategy:

- AKShare is handled interface-by-interface;
- AKShare is not the only data source;
- Tencent `stock_zh_a_hist_tx` is the current primary A-share daily candidate;
- BaoStock remains a validation partner and historical source;
- Eastmoney daily history is unstable for primary use and remains deferred/fallback;
- Eastmoney structured financial statements, earnings, news, and notices remain usable by interface-level policy;
- Sina and THS financial interfaces remain under continued testing;
- structured financial interfaces are the consumption-candidate mainline;
- PDF parsing is downgraded to explanation support and never overwrites structured financial data.

Storage:

- long-term retention prioritizes consumption-ready structured data, production candidates, manifests, QA, provenance, reports, forecasts, and backtests;
- raw, parsed, normalized, smoke outputs, parser intermediates, and validation samples are not default long-term full-retention artifacts;
- cleanup is plan-only and does not delete NAS data.

## Boundaries

- Do not commit local secrets.
- Do not leak tokens.
- Do not open formal trusted consumption unless explicitly requested.
- Do not collect non-China equity time series by default.
- Do not delete NAS large directories.
- Do not modify parse_lab from this repository.

