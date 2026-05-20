# FR Dashboard v1 UX Refinement Report

Generated: 2026-05-20T07:40:33Z

Dashboard v1 has been refined from a form-first engineering prototype into a darker financial
research workspace:

- Overview now presents dashboard-style summary cards, macro/asset mini tables and a verified event ticker.
- Research Console has been renamed to Research Workspace.
- Selected Data Categories are rendered as checkbox/multi-select controls instead of free-text input.
- Fiscal/reporting period controls are hidden unless report/yearbook style categories are selected.
- Generated reports expose download controls for Markdown, JSON, GPT prompt and evidence boundary.
- Report Upload supports paste and Markdown file loading, then classifies Analysis Zone, Forecast Zone and Evidence Zone.
- Macro and Asset dashboards read real `macro_asset_historical_ingestion` outputs.
- Commodity Dashboard v1 adds overview cards, Category View, Exchange View and Custom Chart Builder controls.
- Navigation has exactly one Research Workspace entry; workspace history is merged into the same page.

Historical data currently visible in the dashboard:

- Macro series: 31
- Asset/commodity series: 10
- Records: 86877
- Quality counts: {"quality_passed": 40, "quality_warning": 1}

Commodity data keeps spot/futures/exchange distinctions explicit. Current World Bank Pink Sheet
series are benchmark/average-price evidence, not exchange futures.

The UI remains a new Dashboard architecture and does not use Streamlit.

legacy_streamlit_used = false
no_openai_api_called = true
trusted_consumption_affected = false
