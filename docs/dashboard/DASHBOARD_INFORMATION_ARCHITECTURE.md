# Dashboard Information Architecture

## Role

Dashboard v1 is the local research cockpit. It is not Streamlit and should not be replaced by old Streamlit pages.

## Main Areas

- Overview: macro, rates, FX, commodity, asset, source, QA, and data product summaries.
- Research Workspace: research object, categories, time window, as-of snapshot, statistical report, GPT prompt.
- Macro Dashboard: macro series and release/publish status.
- Asset Class Dashboard: FX, rates, commodities, indices, and proxy signals.
- Commodity Dashboard: category, venue, price type, and chart controls.
- Capital Flow Dashboard: Morningstar, fund/ETF, flow proxy, official universe status, and trust queue.
- Company Dashboard: A-share/H-share watchlists, market data, reports, forecasts, and backtests.
- Report Upload: markdown upload/paste, FINAL_REPORT_JSON extraction, analysis/forecast/evidence zones.
- Data Product Panels: registered products, refresh status, limited-field guard, formal trusted consumption status.

## Current Manual Update Direction

Morningstar manual update is currently dashboard-driven:

- paste token;
- save;
- trigger database update;
- show token status, run status, QA, failure log, and dashboard summary.

## Display Rules

- Show candidate, production candidate, trusted-candidate preview, and blocked statuses honestly.
- Do not hide limited fields.
- Do not claim formal trusted consumption is open.
- Show insufficient evidence, missing publish date, future publish date exclusion, and proxy limitations.

