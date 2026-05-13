# Financial Report Module

`financial_report` is the core financial-report research module inside the broader FinancialResearch platform.

The new architecture does not remove or weaken the original financial-report methodology. It moves the old single-purpose Streamlit workflow into a modular platform where financial reports can connect with macro research, market data, sentiment, research repository, and decision support.

For the complete methodology, see:

- [Financial Report Module Guide](../../../../docs/FINANCIAL_REPORT_MODULE_GUIDE.md)
- [Research Framework](../../../../docs/RESEARCH_FRAMEWORK.md)

## Responsibilities

This module owns the research workflow after PDF parsing:

- Submit PDF parse jobs to Parse Lab through HTTP.
- Poll Parse Lab parse task status.
- Build parse result manifests.
- Classify document type and report role.
- Separate primary time-series reports from auxiliary materials.
- Assess parse quality before downstream extraction.
- Prepare table, text, and metric candidates for financial analysis.
- Support future extraction, forecasting, backtesting, revision, and decision support.

## Financial Report Workflow

```text
PDF / report material input
-> Parse Lab parsing
-> document type recognition
-> primary report vs auxiliary material gate
-> table / text / metric extraction
-> financial analysis
-> forecasting
-> backtesting
-> forecast correction
-> long-term tracking
-> decision support
```

## Current Scope

- Parse Lab HTTP submit and status polling.
- Parse result manifest handling.
- Review and quality gates before extraction.
- Document role / report type gate.
- Dry-run table and statement mapping prototypes.

## Not Yet Production Scope

- Formal financial field extraction.
- Formal metrics extraction.
- Forecasting.
- Backtesting.
- Report generation.
- Persistent database-backed research memory.

## Boundary With Parse Lab

Parse Lab remains an independent PDF parsing service. FinancialResearch does not import Parse Lab internals and does not directly call parser engines such as Marker, MinerU, PaddleOCR, pdfplumber, or PyMuPDF.

FinancialResearch consumes Parse Lab through HTTP APIs or parse output manifests, then applies financial-report research logic, quality gates, extraction, analysis, forecasting, backtesting, and decision support.
