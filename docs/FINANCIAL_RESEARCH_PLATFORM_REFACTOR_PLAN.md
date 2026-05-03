# FinancialResearch Platform Refactor Plan

Generated at: 2026-05-03

## Why Retire Streamlit

The old project was a Streamlit monolith. It was useful for early exploration, but it mixes UI pages, parsing, extraction, analysis, forecast, backtest, and repository behavior in one runtime.

The new direction is a modular financial research platform. That requires:

- clear API boundaries
- backend task orchestration
- frontend/backend separation
- module-level ownership
- explicit integration contracts with external services such as Parse Lab

Streamlit is therefore removed from the new branch rather than preserved as a parallel legacy application.

## New Platform Positioning

FinancialResearch becomes the main research platform. It will host:

- `financial_report`
- `macro_research`
- `sentiment_analysis`
- `market_data_tracking`
- `research_repository`
- `decision_support`
- `system_tasks`

The backend is FastAPI. The frontend will be React + Vite.

## Modular Main Platform Plus Select Independent Services

Most research modules start inside the FinancialResearch backend. Modules should only split into workers or independent services when they require:

- heavy dependencies
- long-running jobs
- real-time collection
- model inference isolation
- independent deployment or scaling

## Why Parse Lab Remains Independent

Parse Lab owns PDF parsing, parser routing, visual table handling, and cross-page table detection. It has separate parser environments and heavier operational constraints.

FinancialResearch calls Parse Lab over HTTP only. It does not import Parse Lab internals and does not directly call Marker, MinerU, Surya, pdfplumber, or PyMuPDF.

## Why Macro/Sentiment/Market Data Stay Internal First

Macro research, sentiment, and market data tracking are domain modules, not yet separate runtime platforms. Keeping them internal reduces deployment complexity while the product shape is still forming.

They can become workers or services later if their dependencies or runtime patterns justify it.

## New Directory Structure

```text
backend/
  app/
    main.py
    core/
    clients/
    modules/
      financial_report/
      macro_research/
      sentiment_analysis/
      market_data_tracking/
      research_repository/
      decision_support/
      system_tasks/
    shared/
frontend_web/
  src/
    api/
    components/
    pages/
requirements/
  backend-api.txt
docs/
```

## Old app/ Deletion Strategy

The old `app/` directory was deleted directly from this branch. It was not moved to `legacy_archive`, and no legacy Streamlit project is retained.

The old code remains recoverable from Git history and the remote repository.

The old project structure was recorded before deletion in:

```text
docs/LOCAL_PROJECT_INVENTORY.md
```

## Future Financial Report Module Rebuild

The financial report module should be rebuilt around Parse Lab API v1:

1. Submit PDF parse task to Parse Lab.
2. Poll Parse Lab task status.
3. Build a result manifest from Parse Lab output paths.
4. Run a parse quality gate.
5. Register parsed documents.
6. Only after review, adapt approved parse outputs into field extraction and metrics workflows.

Do not connect parse output directly to forecasting, backtesting, or report generation until the registry and quality gate are stable.

## Legacy Streamlit Lessons

The Streamlit version was valuable as a prototype, but it exposed stability and maintainability limits around long-running parser tasks, task cancellation, task status visibility, log synchronization, and page-driven business logic.

The detailed lessons and refactor rationale are recorded in:

```text
docs/STREAMLIT_LEGACY_ISSUES_AND_REFACTOR_LESSONS.md
```

Future UI work should keep the frontend thin, backend-driven, and isolated from parser runtimes.

## Expansion Phases

Suggested phases:

1. Backend skeleton and Parse Lab client.
2. Financial report parse registry.
3. Financial field extraction against approved Parse Lab outputs.
4. Research repository and retrieval.
5. Macro, sentiment, and market data modules.
6. Decision support workflows.
7. React frontend.
8. Worker/service split only where justified.
