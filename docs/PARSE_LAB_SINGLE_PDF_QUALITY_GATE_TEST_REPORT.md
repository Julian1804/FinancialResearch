# Parse Lab Single PDF Quality Gate Test Report

Generated at: 2026-05-03

## Scope

This test submits one PDF through the FinancialResearch Parse Lab client and ingestion service, then builds a manifest and runs the parse quality gate.

Not performed:

- No extraction
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab code changes
- No parser environment changes
- No commit or push

## Test PDF

```text
D:\workspace\parse_lab\test_data\华钰矿业2025年一季报告.pdf
```

## Task Result

- `task_id`: `parse_v1_90d6c2ad4232`
- final status: `completed`
- elapsed_seconds: `353.8`
- output_dir: `D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232`

## Manifest

```text
summary_path: D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232\summary.json
pages_jsonl_path: D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232\pages.jsonl
merged_md_path: D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232\merged.md
tables_json_path: D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232\tables.json
merged_tables_json_path: D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232\merged_tables.json
quality_flags_path: D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232\quality_flags.json
cross_page_candidates_path: D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232\cross_page_table_candidates.jsonl
```

## Summary

```json
{
  "pdf_name": "华钰矿业2025年一季报告.pdf",
  "total_pages": 18,
  "parser_usage": {
    "pymupdf": 1,
    "pdfplumber": 17,
    "mineru": 8
  },
  "heavy_parser_ratio": 0.4444,
  "ocr_ratio": 0.0,
  "visual_table_route_pages": [],
  "table_recovery_pages": [],
  "cross_page_table_candidate_count": 16,
  "merged_table_count": 16,
  "failed_pages": [],
  "empty_pages": [],
  "total_elapsed_seconds": 353.8,
  "api_profile": "financial_report_v1_1",
  "routing_policy_version": "v1.1"
}
```

## Quality Gate

- `parse_quality_level`: `pass_with_warnings`
- `parse_quality_reasons`:
  - `cross_page_table_candidate_count=16`
- failed_pages_count: `0`
- empty_pages_count: `0`
- total_pages: `18`
- heavy_parser_ratio: `0.4444`
- ocr_ratio: `0.0`
- visual_table_route_pages_count: `0`
- cross_page_table_candidate_count: `16`
- merged_table_count: `16`

## File Checks

- `pages_count`: `18`
- `summary.total_pages`: `18`
- pages_count matches total_pages: yes
- `merged.md` exists and is non-empty: yes, observed size `62349` bytes
- `quality_flags.json` exists: yes
- cross-page table candidate exists: yes
- visual table route pages exist: no

## Registry Readiness

This result can enter the next parsed document registry stage as a `pass_with_warnings` record. The warning is expected because this PDF contains cross-page table candidates, so downstream consumers should preserve `merged_tables.json` and cross-page candidate metadata.

It should not enter extraction, metrics, forecast, backtest, or report generation until the registry and review policy are explicitly wired.
