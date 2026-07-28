# Financial Report AI-consumable Text Layer Policy

Routing status: `active_methodology`
Authority: routed by `AGENTS.md`; cannot override `FR_CURRENT_STATE.md` or `FR_NEXT_TASK.md`.
Current truth route: `AGENTS.md` -> `docs/FR_CANONICAL_CONTEXT_INDEX.md` -> `docs/FR_CURRENT_STATE.md` -> `docs/FR_NEXT_TASK.md`.


Generated: 2026-05-23T15:52:03Z

Core Data Only does not mean retaining only PDFs and dropping useful text. Financial report PDFs are original evidence, but FR also needs an AI-consumable report text layer for company strategy analysis, financial explanation, forecasting and evidence traceability.

## Long-term Keep

- pdf_original_or_url_path_hash_metadata
- cleaned_canonical_text
- section_text
- semantic_chunks
- key_sections
- evidence_map
- page_anchors
- document_summary
- qa_summary
- manifest
- provenance

## Not Long-term Keep

- raw_parser_debug_output
- ocr_temp_layers
- duplicate_snapshots
- unvalidated_parsed_versions
- unvalidated_normalized_versions
- intermediate_table_text_variants

## Consumption Rule

AI analysis may consume cleaned text, sections, chunks, evidence maps and summaries; parser intermediates cannot override authoritative structured financial interfaces.

PDF parser output is explanatory evidence. It must not override authoritative structured financial interfaces for core financial metrics.
