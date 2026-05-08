# Statement Field Mapping Refinement Report

Generated at: 2026-05-03

## Scope

This report compares the previous statement field mapping prototype with the refined no-LLM mapping rules.

Not performed:

- No PDF parse submission
- No parser execution
- No LLM call
- No formal database write
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes

## Document

- `document_id`: `parsed_doc_22687fab59b569de`

## Before / After

- baseline `fields_count`: `350`
- refined `fields_count`: `47`
- baseline `revenue`: `234`
- refined `revenue`: `11`
- baseline `unknown_unit_count`: `156`
- refined `unknown_unit_count`: `36`
- baseline `unknown_period_count`: `262`
- refined `unknown_period_count`: `32`
- `requires_review_count`: `44`
- `discarded_candidates_count`: `43`
- `average_confidence`: `0.7168`
- `noise_reduced`: `True`

Canonical field distribution:

```json
{
  "revenue": 11,
  "net_profit": 5,
  "net_profit_attributable_parent": 5,
  "shareholder_name": 2,
  "total_assets": 6,
  "total_liabilities": 6,
  "operating_cash_flow": 3,
  "investing_cash_flow": 4,
  "financing_cash_flow": 3,
  "cash_and_cash_equivalents": 2
}
```

Statement type distribution:

```json
{
  "income_statement": 21,
  "shareholder_table": 2,
  "balance_sheet": 14,
  "cash_flow_statement": 10
}
```

Retained candidate examples:

```json
[
  {
    "canonical_field_name": "revenue",
    "raw_field_name": "营业收入",
    "raw_value": "261,347,980.19",
    "period_label": "本报告期",
    "source_pages": [
      2
    ],
    "confidence": 0.95,
    "mapping_reason": "row_alias_match:exact_aliases"
  },
  {
    "canonical_field_name": "net_profit",
    "raw_field_name": "归属于上市公司股东的净利\n润",
    "raw_value": "45,658,532.70",
    "period_label": "本报告期",
    "source_pages": [
      2
    ],
    "confidence": 0.85,
    "mapping_reason": "row_alias_match:phrase_aliases"
  },
  {
    "canonical_field_name": "net_profit_attributable_parent",
    "raw_field_name": "归属于上市公司股东的净利\n润",
    "raw_value": "45,658,532.70",
    "period_label": "本报告期",
    "source_pages": [
      2
    ],
    "confidence": 0.85,
    "mapping_reason": "row_alias_match:phrase_aliases"
  },
  {
    "canonical_field_name": "revenue",
    "raw_field_name": "除上述各项之外的其他营业外收入和支出",
    "raw_value": "-133,494.13",
    "period_label": "unknown_period",
    "source_pages": [
      4
    ],
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "shareholder_name",
    "raw_field_name": "股东名称",
    "raw_value": "持有无限售条件流通股的数量",
    "period_label": "unknown_period",
    "source_pages": [
      5
    ],
    "confidence": 0.73,
    "mapping_reason": "row_alias_match:exact_aliases"
  },
  {
    "canonical_field_name": "total_assets",
    "raw_field_name": "资产总计",
    "raw_value": "5,653,743,362.58",
    "period_label": "unknown_period",
    "source_pages": [
      8
    ],
    "confidence": 0.73,
    "mapping_reason": "row_alias_match:exact_aliases"
  },
  {
    "canonical_field_name": "total_liabilities",
    "raw_field_name": "负债合计",
    "raw_value": "1,517,483,288.58",
    "period_label": "unknown_period",
    "source_pages": [
      9
    ],
    "confidence": 0.73,
    "mapping_reason": "row_alias_match:exact_aliases"
  },
  {
    "canonical_field_name": "revenue",
    "raw_field_name": "一、营业总收入",
    "raw_value": "261,347,980.19",
    "period_label": "2025年第一季度",
    "source_pages": [
      9
    ],
    "confidence": 0.76,
    "mapping_reason": "row_alias_match:phrase_aliases"
  },
  {
    "canonical_field_name": "revenue",
    "raw_field_name": "加：营业外收入",
    "raw_value": "101,262.20",
    "period_label": "unknown_period",
    "source_pages": [
      10
    ],
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "operating_cash_flow",
    "raw_field_name": "经营活动产生的现金流量净额",
    "raw_value": "23,000,841.80",
    "period_label": "unknown_period",
    "source_pages": [
      12
    ],
    "confidence": 0.73,
    "mapping_reason": "row_alias_match:exact_aliases"
  }
]
```

Discarded candidate examples:

```json
[
  {
    "canonical_field_name": "revenue",
    "raw_field_name": "其中：营业收入",
    "raw_value": "261,347,980.19",
    "table_id": "page_table_9_1",
    "confidence": 0.59,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "operating_cash_flow",
    "raw_field_name": "经营活动现金流入小计",
    "raw_value": "273,141,777.94",
    "table_id": "page_table_12_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "operating_cash_flow",
    "raw_field_name": "支付其他与经营活动有关的现金",
    "raw_value": "16,366,477.29",
    "table_id": "page_table_12_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "operating_cash_flow",
    "raw_field_name": "经营活动现金流出小计",
    "raw_value": "250,140,936.14",
    "table_id": "page_table_12_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "operating_cash_flow",
    "raw_field_name": "收到其他与经营活动有关的现金",
    "raw_value": "878,563.67",
    "table_id": "page_table_12_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "investing_cash_flow",
    "raw_field_name": "投资活动现金流出小计",
    "raw_value": "63,294,424.54",
    "table_id": "page_table_13_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "financing_cash_flow",
    "raw_field_name": "筹资活动现金流入小计",
    "raw_value": "40,366,386.05",
    "table_id": "page_table_13_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "financing_cash_flow",
    "raw_field_name": "支付其他与筹资活动有关的现金",
    "raw_value": "10,715,582.23",
    "table_id": "page_table_13_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "financing_cash_flow",
    "raw_field_name": "筹资活动现金流出小计",
    "raw_value": "29,905,377.83",
    "table_id": "page_table_13_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  },
  {
    "canonical_field_name": "financing_cash_flow",
    "raw_field_name": "收到其他与筹资活动有关的现金",
    "raw_value": "40,366,386.05",
    "table_id": "page_table_13_0",
    "confidence": 0.46,
    "mapping_reason": "row_alias_match:weak_aliases"
  }
]
```

Warnings:

```json
[
  "override_used",
  "eligibility_block_reason=review_decision=needs_reparse; approved_for_extraction=false",
  "discarded_candidates_count=43"
]
```

Errors:

```json
[]
```

## Remaining Issues

- Unit and currency detection still depends mostly on table-local text; surrounding page text should be added.
- Period detection improves only when table headers retain clear period labels.
- Cross-page numeric repair is still not implemented.
- Shareholder table extraction needs table-specific logic for name, count, ratio, and pledge columns.

## Readiness

The refined mapping reduces candidate noise and can proceed to a minimal financial statement extraction prototype, still as dry-run and behind source traceability checks.
