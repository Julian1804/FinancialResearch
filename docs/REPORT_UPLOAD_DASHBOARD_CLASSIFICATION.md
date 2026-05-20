# Report Upload Dashboard Classification

Generated: 2026-05-20T06:18:11Z

Report Upload v1 parses a pasted Markdown report containing `FINAL_REPORT_JSON`, validates the
minimum schema, preserves raw text, and classifies output into:

- Analysis Zone
- Forecast Zone
- Evidence Zone

Sample schema_valid: true

GPT report content remains an analysis_report / forecast / interpretation artifact, not a trusted fact.
