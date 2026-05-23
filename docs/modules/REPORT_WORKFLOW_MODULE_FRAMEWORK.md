# Report Workflow Module Framework

## Purpose

The report workflow converts governed data into research packets and then structures user-provided GPT Web reports back into FR.

## Workflow

```text
Research Workspace selection
-> as-of snapshot
-> statistical_report.json / .md
-> copy_to_gpt_prompt.md
-> user discusses in GPT Web
-> user uploads final report
-> FINAL_REPORT_JSON extraction
-> analysis / forecast / evidence classification
-> structured storage
```

## Rules

- FR does not call OpenAI API in this workflow.
- GPT report text is not trusted fact.
- Candidate and trusted-candidate labels must be preserved.
- Insufficient evidence must remain visible.
- As-of date and information boundary must be respected.

## Output Zones

- Analysis Zone: interpretation, causal chain, sector/company judgment.
- Forecast Zone: testable forecast, risk trigger, review date, confidence.
- Evidence Zone: packet ID, sources, publish window, trust labels, limitations.

