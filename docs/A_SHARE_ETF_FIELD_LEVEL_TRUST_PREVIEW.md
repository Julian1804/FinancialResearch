# A-Share / ETF Field-Level Trust Preview

OHLC is the first trusted candidate preview data product for the controlled A-share / ETF watchlist.

Limited field upgrade path:

```json
{
  "generated_at": "2026-05-21T08:24:07Z",
  "fields": {
    "amount": {
      "current_status": "ready_for_trusted_candidate_limited",
      "required_evidence_to_upgrade": [
        "secondary source amount coverage",
        "unit normalization evidence",
        "cross-source tolerance policy",
        "QA pass over expanded watchlist"
      ]
    },
    "turnover_rate": {
      "current_status": "ready_for_trusted_candidate_limited",
      "required_evidence_to_upgrade": [
        "documented source definition",
        "secondary source coverage",
        "reasonable range QA",
        "expanded cross-source validation"
      ]
    },
    "pct_change": {
      "current_status": "ready_for_trusted_candidate_limited",
      "required_evidence_to_upgrade": [
        "deterministic formula or upstream definition",
        "preclose/adjustment policy",
        "precision tolerance rule",
        "mismatch review queue closure"
      ]
    },
    "preclose": {
      "current_status": "ready_for_trusted_candidate_limited",
      "required_evidence_to_upgrade": [
        "secondary source coverage or audited derivation from previous close",
        "corporate action adjustment mode policy",
        "cross-source validation after ex-right/ex-dividend cases"
      ]
    }
  }
}
```

Limited field review:

```json
{
  "generated_at": "2026-05-21T08:24:07Z",
  "limited_fields": {
    "amount": {
      "current_status": "ready_for_trusted_candidate_limited",
      "warning": "Excluded from trusted_candidate preview.",
      "reason": "AKShare Tencent normalized sample does not provide consistent amount coverage."
    },
    "turnover_rate": {
      "current_status": "ready_for_trusted_candidate_limited",
      "warning": "Excluded from trusted_candidate preview.",
      "reason": "Secondary source support/definition agreement is not available in the current controlled sample."
    },
    "pct_change": {
      "current_status": "ready_for_trusted_candidate_limited",
      "warning": "Excluded from trusted_candidate preview.",
      "reason": "Needs deterministic source definition or formula validation and tolerance policy."
    },
    "preclose": {
      "current_status": "ready_for_trusted_candidate_limited",
      "warning": "Excluded from trusted_candidate preview.",
      "reason": "Needs secondary-source coverage or documented derivation policy across corporate action adjustment modes."
    }
  },
  "formal_trusted_consumption": false
}
```
