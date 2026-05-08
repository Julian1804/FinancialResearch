# Document Role Gate Test Report

Generated at: 2026-05-03

## Why This Gate Exists

Only primary time-series financial reports should be expected to contain the three main financial statements.

Earnings releases, result announcements, performance briefings, conference call transcripts, and investor presentations often contain selected performance metrics, management commentary, or slides. They should not be penalized for missing balance sheet, income statement, or cash flow statement tables.

## Classification Results

```json
[
  {
    "document_id": "",
    "pdf_name": "华钰矿业2025年一季报告.pdf",
    "document_role": "primary_financial_report",
    "report_type": "q1_report",
    "expects_three_statements": true,
    "expected_extraction_strategy": "three_statement_extraction",
    "confidence": 0.88,
    "evidence": [
      "filename:一季报"
    ],
    "requires_review": false
  },
  {
    "document_id": "",
    "pdf_name": "华钰矿业2024年年报.pdf",
    "document_role": "primary_financial_report",
    "report_type": "annual_report",
    "expects_three_statements": true,
    "expected_extraction_strategy": "three_statement_extraction",
    "confidence": 0.88,
    "evidence": [
      "filename:年报"
    ],
    "requires_review": false
  },
  {
    "document_id": "",
    "pdf_name": "药明生物2024年报.pdf",
    "document_role": "primary_financial_report",
    "report_type": "annual_report",
    "expects_three_statements": true,
    "expected_extraction_strategy": "three_statement_extraction",
    "confidence": 0.88,
    "evidence": [
      "filename:年报"
    ],
    "requires_review": false
  },
  {
    "document_id": "",
    "pdf_name": "药明生物2021全年业绩新闻稿_En.pdf",
    "document_role": "auxiliary_material",
    "report_type": "earnings_release",
    "expects_three_statements": false,
    "expected_extraction_strategy": "auxiliary_performance_extraction",
    "confidence": 0.86,
    "evidence": [
      "filename:业绩新闻稿"
    ],
    "requires_review": false
  },
  {
    "document_id": "",
    "pdf_name": "药明生物2025全年业绩简报.pdf",
    "document_role": "auxiliary_material",
    "report_type": "earnings_presentation",
    "expects_three_statements": false,
    "expected_extraction_strategy": "auxiliary_performance_extraction",
    "confidence": 0.86,
    "evidence": [
      "filename:业绩简报"
    ],
    "requires_review": false
  },
  {
    "document_id": "",
    "pdf_name": "泡泡玛特2025年业绩公告.pdf",
    "document_role": "auxiliary_material",
    "report_type": "earnings_announcement",
    "expects_three_statements": false,
    "expected_extraction_strategy": "auxiliary_performance_extraction",
    "confidence": 0.86,
    "evidence": [
      "filename:业绩公告"
    ],
    "requires_review": false
  },
  {
    "document_id": "",
    "pdf_name": "某公司电话会议纪要.pdf",
    "document_role": "auxiliary_material",
    "report_type": "conference_call_transcript",
    "expects_three_statements": false,
    "expected_extraction_strategy": "transcript_or_commentary_extraction",
    "confidence": 0.86,
    "evidence": [
      "filename:电话会议"
    ],
    "requires_review": false
  }
]
```

## Expects Three Statements

```json
[
  "华钰矿业2025年一季报告.pdf",
  "华钰矿业2024年年报.pdf",
  "药明生物2024年报.pdf"
]
```

## Does Not Require Three Statements

```json
[
  "药明生物2021全年业绩新闻稿_En.pdf",
  "药明生物2025全年业绩简报.pdf",
  "泡泡玛特2025年业绩公告.pdf",
  "某公司电话会议纪要.pdf"
]
```

## Impact On Extraction Adapter

- `primary_financial_report` routes to `three_statement_extraction`.
- `auxiliary_material` routes to auxiliary performance or commentary extraction.
- `unknown` requires review before any formal extraction.
- Missing three statements should not be treated as a failure for auxiliary materials.

## Next Auxiliary Material Route

Future auxiliary extraction should handle:

- key performance metric snippets;
- management commentary;
- investor presentation tables;
- conference call transcript sections;
- source traceability separate from three-statement extraction.
