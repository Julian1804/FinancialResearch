# Parsed Document Registry Test Report

Generated at: 2026-05-03

## Scope

This test registers one completed Parse Lab API v1 parse result into a local JSONL parsed document registry.

Not performed:

- No extraction
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes
- No parser environment changes
- No commit or push

## Input

- `task_id`: `parse_v1_90d6c2ad4232`
- `pdf_path`: `D:\workspace\parse_lab\test_data\华钰矿业2025年一季报告.pdf`

## Registry

Registry path:

```text
D:\workspace\FinancialResearch\runtime\financial_report\parsed_document_registry.jsonl
```

The registry is local JSONL. It stores parse output references and quality metadata only. It does not copy Parse Lab output files and does not create legacy `parsed_*.json`.

## Registered Entry

- `document_id`: `parsed_doc_22687fab59b569de`
- `parse_task_id`: `parse_v1_90d6c2ad4232`
- `parse_status`: `completed`
- `parse_quality_level`: `pass_with_warnings`
- `parse_quality_reasons`:
  - `cross_page_table_candidate_count=16`
- `output_dir`: `D:\workspace\runtime\parse_lab\results\api_v1\parse_v1_90d6c2ad4232`

Stored reference fields:

- `summary_path`
- `pages_jsonl_path`
- `merged_md_path`
- `tables_json_path`
- `merged_tables_json_path`
- `quality_flags_path`
- `cross_page_candidates_path`

Stored quality summary:

- `total_pages`: `18`
- `failed_pages_count`: `0`
- `empty_pages_count`: `0`
- `heavy_parser_ratio`: `0.4444`
- `ocr_ratio`: `0.0`
- `visual_table_route_pages_count`: `0`
- `cross_page_table_candidate_count`: `16`
- `merged_table_count`: `16`

## Lookup Validation

- `find_by_task_id("parse_v1_90d6c2ad4232")`: success
- `find_by_pdf_path(pdf_path)`: success
- task match count: `1`
- PDF match count: `1`

## Next Stage Readiness

The registry can enter the next design stage:

- review queue design
- extraction adapter design

The next stage should still keep `pass_with_warnings` records visible as warnings and preserve cross-page table metadata. It should not automatically enter extraction, metrics, forecast, backtest, or report generation until those adapters are explicitly designed and tested.
