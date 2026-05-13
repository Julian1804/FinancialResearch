# Module Documentation Governance

## Core Principle

The root `README.md` is the platform overview, module navigation, and startup guide. It must not become the home for every module's full methodology.

At the same time, keeping the root README concise must never mean deleting or compressing away a module's methodology, theory, workflow, or data model.

## Required Rule

When documentation is refactored:

1. Do not delete module methodology to make the root README shorter.
2. Move or preserve detailed module content in that module's own documentation.
3. Confirm the detailed module documentation exists before simplifying the root README.
4. Keep the root README as a concise map with links to module-level documents.
5. Treat missing module methodology as a documentation regression.

## Module Documentation Standard

Each business module should maintain its own documentation set over time:

- `README.md`: module positioning, responsibilities, boundaries, and links.
- `METHODOLOGY.md`: theory, research framework, analytical principles, and assumptions.
- `WORKFLOW.md`: end-to-end process, states, review gates, and operational flow.
- `DATA_SCHEMA.md`: core entities, fields, provenance, validation status, and output contracts.

The exact file names may vary, but the content must remain discoverable from the module README.

## Applies To

This rule applies to all FinancialResearch business modules, including:

- `financial_report`
- `macro_research`
- `sentiment_analysis`
- `market_data_tracking`
- `research_repository`
- `decision_support`
- future modules added to the platform

## Current Financial Report Example

The `financial_report` module keeps its detailed methodology in:

- [FINANCIAL_REPORT_MODULE_GUIDE.md](FINANCIAL_REPORT_MODULE_GUIDE.md)
- [backend/app/modules/financial_report/README.md](../backend/app/modules/financial_report/README.md)
- [RESEARCH_FRAMEWORK.md](RESEARCH_FRAMEWORK.md)

The root README only links to these documents and summarizes the module's role.

## Review Checklist

Before simplifying any platform-level documentation, verify:

- The module's full methodology is preserved.
- The module's workflow is preserved.
- The module's data/schema principles are preserved or explicitly linked.
- The root README links to the detailed module documentation.
- No important analytical framework was removed without a replacement location.

If any answer is no, do not simplify the root README yet.
