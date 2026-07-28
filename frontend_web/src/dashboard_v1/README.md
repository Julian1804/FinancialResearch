# FR Workspace Shell v1 (Read Model Refresh Required)

This frontend is retained as a stale read-model consumer during the unified
metric/fact migration. Its prior action server and one-off update routes are
historical and non-authoritative. Do not launch it until a reader backed by
`standard_facts`, `config/metrics_registry.json`, and
`config/fr_dataset_registry.json` is accepted.

Launch status: `disabled_read_model_refresh_required`.

## Workspace V1 Structure

The default shell stays dependency-free and uses browser-native ES modules:

```text
index.html
workspace_v1/
  styles/workspace.css
  js/state.js
  js/api.js
  js/components.js
  js/navigation.js
  js/view-registry.js
  js/ai-bridge.js
  js/views/
```

Keep backend calls in `api.js`, shared card-density rules in `components.js`,
and product-facing screens under `js/views/`. Do not rebuild the single-file
shell pattern.

Workspace extension registries:

- `config/fr_app_registry.json`: internal functional and plugin entry points.
- `config/fr_dashboard_registry.json`: Dashboard -> Tabs -> Module Slots.
- `config/fr_module_registry.json`: reusable Module contracts.

The compact shell reads these through `/api/workspace/bootstrap`. Apps,
Modules, and Dashboards are separate product concepts. V1 does not load remote
third-party JavaScript.

## Dashboard Product Boundaries

- Overview, Database, Modeling Workbench, Agent Simulation, and Connections are
  the ordinary Research Workspace surfaces.
- My Dashboards is secondary workspace management.
- Dashboard Detail uses Tabs and shared Module Slots.
- Plug-in Library and Apps are compatibility/secondary surfaces, not ordinary
  Research Workspace primary navigation.
- Connections is the source, token, refresh, and runtime-status surface.
- Default registry Dashboards remain immutable. Add Dashboard and Add Module
  write only small versioned JSON snapshots under `docs/FR_RETAINED_CONCLUSION_INDEX.md`.
  They do not write registry or data-lake state.
- Dashboard Detail saves lightweight Notes and Report Drafts. AI Bridge saves
  bounded local AI Handoff Drafts without calling an AI API.
- The right panel is page-owned on ordinary task pages. Dashboard context export
  is available from My Dashboards and Dashboard Detail only.

## Modeling Workbench Diagnostic Boundary

- Preview validates data availability, summary statistics, and final sample
  without executing a model.
- Run requires an explicit user action and is diagnostic-only.
- Enabled model families: `ols`, `rolling_ols`.
- Disabled families remain visible with exact reasons: descriptive preview-only,
  correlation adapter not connected, regularization adapters not connected, PCA
  adapter not connected, tree-model adapter not connected, and time-series or
  regime adapters not connected.
- Result tabs must render model results, chart panels, and backend run history
  after a successful diagnostic run.
- Ordinary UI must not expose raw request echo technical details.
- No production write, Observation write, runtime update writer, external
  provider call, raw-lake scan, prediction, backtest, trading signal, portfolio
  recommendation, or investment-advice claim is allowed.

## Data-Series Drill-down

- Each Dashboard Module Slot exposes `View Data Series`.
- The list stays compact: name, category, source, latest date, status, proxy
  label, and chart-adapter state.
- Allowlisted Series can open a small SVG trend through
  `/api/modules/timeseries`.
- Source gaps and Series that require company selection remain explicit.
- `Use Series in AI` adds the selected Series and lookback range to the local
  copy-paste context pack. No AI API is called.

`legacy_streamlit_used = false`.
