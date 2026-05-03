# Streamlit Legacy Issues And Refactor Lessons

Generated at: 2026-05-03

## 1. Legacy Streamlit Architecture

The previous FinancialResearch implementation was organized around a Streamlit application:

- `app/main.py`
- `app/pages/*`
- `app/services/*`
- `app/agents/*`
- `app/config/*`

This structure was effective for early experiments because pages could quickly call service functions and show intermediate outputs. Over time, page rendering, parsing orchestration, extraction behavior, task state, logs, and analysis workflows became coupled inside one runtime.

The same pattern also appeared in Parse Lab UI experiments: UI interaction and long-running parser tasks were too close to each other.

## 2. Issues Observed In The Streamlit Stage

UI stability issues:

- Page refresh, sidebar navigation, and task detail switching could disconnect or restart the app.
- Long task state was fragile when the Streamlit process reran scripts.
- Users could lose confidence in whether an action was still running.

Long-task blocking issues:

- Parser tasks and UI rendering shared runtime pressure.
- Heavy PDF parsing could make the whole page slow or unavailable.
- The UI process was not a reliable long-running job supervisor.

Cancel, hung, and queued state issues:

- Cancel actions could mark a task as cancelled while a background parser process still occupied resources.
- Queued, running, and hung states were sometimes difficult to distinguish.
- Marker, MinerU, Surya, and Docling style heavy parsers made state detection especially important.

Logs and task status drift:

- Logs could show activity while task metadata looked stale.
- Task metadata could show running while the actual process was hung or gone.
- Users lacked a clear source of truth for parser, elapsed time, output path, and final status.

Parser observability issues:

- Old task records did not always preserve complete parser usage, final parser source, task id, elapsed seconds, or route details.
- Heavy parser use was hard to audit after the fact.
- Parser-specific failures were not cleanly separated from business-level parsing quality.

Resource issues:

- Running heavy parsers across an entire PDF was expensive.
- Full-document Marker, MinerU, Surya, or Docling runs could pressure CPU, GPU, memory, and page file usage.
- One bad PDF or route could degrade the interactive experience.

Platform expansion issues:

- UI pages and business logic were mixed across `app/pages` and `app/services`.
- Adding macro research, sentiment analysis, market data tracking, research repository, and decision support would make the monolith harder to maintain.
- Streamlit is valuable for prototypes, but it is not the right long-term dashboard architecture for this financial research platform.

## 3. Why Streamlit Is Not Retained

Retiring Streamlit is not a rejection of the prototype. The prototype was useful: it proved workflows, surfaced parser failures, and clarified what the platform must become.

The project has moved from prototype mode into long-term platform design. That stage needs:

- frontend/backend separation;
- asynchronous task orchestration;
- stable HTTP APIs;
- task registry and parsed document registry;
- review queue and approval gates;
- modular backend ownership;
- independent parser service boundaries.

For those reasons, the legacy Streamlit application was removed from the current refactor branch instead of being retained as a parallel legacy app.

## 4. How The New Architecture Addresses These Issues

FastAPI backend:

- Owns platform APIs and business orchestration.
- Keeps task metadata, registry entries, review queue, review decisions, and eligibility gates outside the UI runtime.

React frontend:

- Will call only FinancialResearch backend APIs.
- Will not run parser tasks directly.
- Can become a stable dashboard without owning long-running processes.

Parse Lab independent service:

- Owns parser dependencies and PDF parsing orchestration.
- Keeps Marker, MinerU, Surya, Docling, pdfplumber, and routing details outside FinancialResearch.
- Exposes a stable API boundary instead of parser internals.

HTTP-only Parse Lab boundary:

- FinancialResearch does not import Parse Lab internal modules.
- FinancialResearch does not install parser dependencies in its main backend environment.
- Parser failures remain isolated from the main research platform.

Registry and review model:

- Task registry tracks parse tasks.
- Parsed document registry stores output references and quality levels.
- Review queue exposes documents that need attention.
- Review decisions explicitly control whether a parsed document may enter extraction.
- Extraction eligibility gate prevents accidental downstream processing.

Routing and resource control:

- Parse Lab V1.1 uses page-level routing.
- Heavy parsers are not run across every page by default.
- Visual table and cross-page table handling are targeted to pages that need them.

Traceability:

- Parse outputs preserve `quality_flags`, `source_pages`, `table_group_id`, `continuation_confidence`, parser source, and route fields.
- Downstream extraction prototypes carry source references instead of producing untraceable numbers.

Module platform:

- FinancialResearch is organized around backend modules:
  - `financial_report`
  - `macro_research`
  - `sentiment_analysis`
  - `market_data_tracking`
  - `research_repository`
  - `decision_support`
  - `system_tasks`
- Macro, sentiment, and market data remain internal modules first, not premature microservices.

## 5. Future Development Principles

- Do not put heavy business logic in the UI layer.
- Do not let the frontend call Parse Lab directly.
- Do not install parser dependencies into the FinancialResearch backend environment.
- Do not let parser tasks run inside the frontend runtime.
- Do not let parsed outputs without review decisions enter extraction.
- Do not let `needs_reparse`, `rejected`, `ignored`, or `pending_review` documents enter automatic extraction.
- Do not penalize auxiliary materials for missing three financial statements.
- Do not assume every document is a primary financial report.
- Do not split macro, sentiment, or market data modules into independent APIs until heavy dependencies, long tasks, real-time collection, model inference, or deployment needs justify it.
- Keep source traceability and quality flags attached to every downstream extraction candidate.
