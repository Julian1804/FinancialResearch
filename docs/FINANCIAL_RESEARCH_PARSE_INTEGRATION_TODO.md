# FinancialResearch Parse Integration TODO

Generated at: 2026-05-03

## Next Stages

1. Financial report parse debug page or CLI entry
   - Submit Parse Lab parse tasks from FinancialResearch.
   - Show task status, registry entry, and review queue state.
   - Do not trigger extraction automatically.
   - Review legacy Streamlit lessons before adding new UI features.
   - Keep UI thin and backend-driven.
   - Do not reintroduce long-running parser tasks into frontend runtime.
   - Keep Parse Lab isolated from the FinancialResearch backend environment.
   - Run automated validation suite before each major refactor.
   - Generate human review pack for semantic/numeric verification only.
   - Do not delegate machine-checkable conditions to the user.
   - Rank high-risk extraction candidates before manual review.
   - Build review result recording mechanism.

2. Parsed document registry persistence strategy
   - Current storage is local JSONL.
   - Decide when to move to SQLite or application database.
   - Keep Parse Lab output paths as references, not copied blobs.

3. Review queue human confirmation mechanism
   - Add explicit review statuses.
   - Support approval, rejection, and notes.
   - Preserve quality reasons and source output paths.
   - Add review decision UI for pending, approved, rejected, needs-reparse, and ignored states.
   - Maintain an approved documents list for downstream extraction candidates.

4. Parse Lab output to financial extraction adapter
   - Design a controlled adapter from `merged.md`, `tables.json`, and `merged_tables.json`.
   - Do not recreate the old Streamlit `parsed_*.json` path unless a compatibility layer is explicitly approved.
   - Enforce the extraction eligibility gate before any adapter execution.

5. Table output standardization
   - Normalize `tables.json` and `merged_tables.json`.
   - Preserve `source_pages`, `table_group_id`, and confidence fields.
   - Review the canonical table schema before enabling extraction.
   - Add table normalization quality checks for empty cells, numeric density, and missing source pages.

6. Financial statement template mapping
   - Map statement tables and common financial rows.
   - Keep company-specific and report-format-specific exceptions traceable.
   - Design financial statement template mapping before automatic field extraction.
   - Build a financial statement template mapping prototype.

7. Extraction / metrics / forecast / backtest integration plan
   - Add document role classification.
   - Route primary reports separately from auxiliary materials.
   - Design auxiliary material extraction strategy.
   - Design conference call / commentary extraction strategy.
   - Do not penalize auxiliary materials for missing three financial statements.
   - Wire only reviewed parse outputs into extraction.
   - Keep metrics, forecast, backtest, and report generation behind separate gates.
   - Add regression tests before enabling any automatic downstream flow.
   - Build a controlled extraction prototype behind the eligibility gate.
   - Add extraction candidate review before statement-specific field mapping.
   - Build a statement-specific field mapping prototype.
   - Add statement field mapping review.
   - Review refined statement mapping candidates.
   - Add table header normalization.
   - Add period column detection.
   - Improve period detection for quarterly, annual, and year-end columns.
   - Add unit and currency detection.
   - Improve unit and currency normalization from surrounding page text.
   - Improve table title detection.
   - Improve surrounding text extraction.
   - Add source page/table visual review link.
   - Add cross-page numeric repair.
   - Add shareholder table special extraction.
   - Build a minimal financial statement extraction prototype.
   - Review minimal extraction results.
   - Review extracted field confidence.
   - Add field-level source traceability.
   - Add review UI / CLI for extracted fields.
   - Define metric handoff schema.
   - Design metrics handoff schema.
   - Add source-page traceability tests.
   - Add source traceability regression tests.
   - Build a no-LLM baseline extraction before any LLM extraction.
   - Design LLM extraction prompts with canonical table evidence references.
   - Add extraction regression tests before connecting metrics or forecast.
