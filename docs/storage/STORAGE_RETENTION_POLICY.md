# Storage Retention Policy

This document is the project-level storage-retention entry point. Detailed policy is also represented in `config/storage_retention_policy.json` and `docs/STORAGE_RETENTION_POLICY_V1.md`.

## Core Rule

Keep the smallest set of artifacts needed for analysis, AI packet generation, forecast, backtest, revision, provenance, QA, and audit.

## Long-Term Keep

- Consumption-ready structured data.
- Production-candidate structured data.
- Financial abstracts and structured statements.
- Daily market structured data.
- Announcement metadata.
- PDF URL / local path / hash.
- AI-consumable report summaries.
- Analysis reports.
- Forecast reports.
- Backtest results.
- Manifest.
- QA summary.
- Provenance summary.
- Data product panel and latest pointer.

## Short-Term Keep

- Raw API responses.
- Smoke test output.
- Temporary snapshots.
- Parser intermediates.
- Candidate validation samples.
- Cross-source validation samples.
- Debug output.

## Cleanup Candidates

- Probe/debug files.
- Duplicate raw files.
- Expired smoke tests.
- Temporary parser output.
- Useless cross-validation intermediate after summary is retained.
- Large raw/parsed/normalized duplicate layers after validated product is created.
- Duplicate snapshots.

## NAS Safety

This policy does not delete NAS data. It generates cleanup plans only. Deleting or moving NAS large directories requires a separate explicit task and user approval.

## PDF Strategy

PDFs can be retained as raw files where audit or explanation requires it. Otherwise PDF URL + path + hash + metadata is often enough. Parser intermediates are not long-term full-retention artifacts.

