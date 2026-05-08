# Human Review Pack Guide

Generated at: 2026-05-04

## Purpose

The human review pack contains only items that require semantic or numeric judgment against the original PDF.

Latest generated pack:

```text
runtime/financial_report/human_review_pack
```

Latest observed item count:

```text
30
```

It intentionally excludes objective checks such as:

- Python compile success
- file existence
- JSON parsing
- registry JSONL parsing
- API health
- pages.jsonl row count matching `summary.total_pages`
- runtime directory existence
- `.gitignore` hygiene

Those are handled by the automated validation suite.

## What Requires Human Review

Human review is needed for:

- cross-page numeric continuity;
- field mapping semantics;
- low-confidence table or statement type classification;
- OCR or visual table recovery correctness;
- document role ambiguity.

## Cross-Page Numeric Checks

For `cross_page_numeric_check` items:

1. Open the original PDF at `source_pages`.
2. Locate `table_group_id` if available in Parse Lab outputs.
3. Confirm whether the number is complete across the page boundary.
4. Verify period, unit, and currency.
5. Record whether the extracted value should be accepted, corrected, or rejected.

## Field Mapping Checks

For `field_mapping_semantic_check` items:

1. Compare `raw_field_name` with the PDF row label.
2. Confirm that `canonical_field_name` is semantically correct.
3. Confirm that `raw_value` belongs to the intended period column.
4. Check `unit`, `currency`, and `period_label`.
5. Mark uncertain weak-alias matches for rule refinement.

## OCR / Visual Table Checks

For `visual_table_check` items:

1. Open the corresponding PDF page.
2. Confirm whether the visual table exists.
3. Check whether the recovered table structure matches the PDF.
4. Mark missing rows, broken columns, or rotated/vertical text problems.

## Document Role Checks

For `auxiliary_material_role_check` items:

1. Confirm whether the PDF is a primary financial report or auxiliary material.
2. Do not penalize auxiliary materials for missing three financial statements.
3. If an auxiliary material contains many statement-like tables, decide whether it should enter a separate auxiliary extraction route.

## Recording Human Conclusions

Future review result recording should capture:

- `review_item_id`
- reviewer
- accepted / corrected / rejected / needs_reparse
- corrected value if applicable
- notes
- reviewed_at

Until that mechanism exists, the review pack is a checklist and evidence bundle only.
