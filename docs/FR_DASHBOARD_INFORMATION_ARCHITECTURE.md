# FR Dashboard Information Architecture

Generated: 2026-05-21T10:28:19Z

Dashboard v1 is a new FinancialResearch workbench UI, not the archived Streamlit interface.

Core pages:

- Overview: data source status, recent snapshots, reports, pending review and missing publish_date.
- Research Workspace: research object/theme selection, data categories, time mode and report generation.
- Macro Dashboard: current official/candidate macro samples and evidence gaps.
- Asset Class Dashboard: commodity/rate/asset-class sample coverage and gaps.
- Commodity Dashboard: commodity overview cards, Category View, Exchange View and Custom Chart Builder.
- Sector Dashboard: schema and insufficient_evidence until sector connectors exist.
- Company Dashboard: watchlist market data, packets, reports, forecasts and backtests.
- Capital Flow Dashboard: framework for ETF/fund/flow data; current data is insufficient.
- Report Upload: paste/upload GPT Web final report, classify into Analysis Zone, Forecast Zone and Evidence Zone.

Research object abstraction supports company, sector, asset_class, macro_theme, capital_flow_theme,
event, geopolitical_event, policy_event, black_swan_event and custom_topic.

New UI smoke:

- tested_url: http://127.0.0.1:5188/
- legacy_streamlit_used: false
- old_ui_false_positive_guard: true
- detected markers: 102

Config outputs:

- D:\workspace\FinancialResearch\config\data_taxonomy.json
- D:\workspace\FinancialResearch\config\time_semantics.json
- D:\workspace\FinancialResearch\config\research_object_types.json
