# Storage Retention Policy v1

Generated: 2026-05-23T10:05:16Z

This policy creates a cleanup plan only. It does not delete NAS data.

Long-term retention favors consumption-ready structured data, production candidates, manifests, QA summaries, provenance summaries, analysis reports, forecasts, backtests and key PDF metadata. Short-term retention covers raw API responses, smoke outputs, parser intermediates and validation samples.

FR should not retain raw, parsed and normalized full-size duplicate layers forever unless audit requirements justify it.
