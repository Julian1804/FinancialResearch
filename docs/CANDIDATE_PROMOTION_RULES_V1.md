{
  "version": "candidate_promotion_rules_v1",
  "generated_at": "2026-05-21T05:44:22Z",
  "states": [
    {
      "status": "candidate",
      "conditions": [
        "raw source is reachable or cached",
        "source role classified"
      ],
      "evidence_required": [
        "source_id",
        "retrieved_at or retrieval snapshot"
      ],
      "downgrade_conditions": [
        "source terms unclear with material risk",
        "schema cannot be interpreted"
      ]
    },
    {
      "status": "schema_validated_candidate",
      "conditions": [
        "schema fields present",
        "date parseable",
        "unit/currency classified",
        "checksum present",
        "QA non-failing"
      ],
      "evidence_required": [
        "normalized schema",
        "quality report",
        "raw checksum"
      ],
      "downgrade_conditions": [
        "required field missing",
        "duplicate key failure",
        "unit ambiguity blocks interpretation"
      ]
    },
    {
      "status": "cross_validated_candidate",
      "conditions": [
        "two independent sources match core fields",
        "differences are explainable and queued if needed"
      ],
      "evidence_required": [
        "cross-source validation report",
        "field-level comparison",
        "mismatch review queue"
      ],
      "downgrade_conditions": [
        "unexplained core-field mismatch",
        "source dependency not independent"
      ]
    },
    {
      "status": "freshness_validated_candidate",
      "conditions": [
        "latest observation and retrieved_at fit expected cadence",
        "release lag known or bounded"
      ],
      "evidence_required": [
        "latest_observation",
        "latest_retrieved_at",
        "next_expected_update"
      ],
      "downgrade_conditions": [
        "stale beyond expected lag",
        "missing date fields"
      ]
    },
    {
      "status": "field_validated_candidate",
      "conditions": [
        "critical fields complete above threshold",
        "identifier/date fields clear"
      ],
      "evidence_required": [
        "field completeness score",
        "identifier fields",
        "date fields"
      ],
      "downgrade_conditions": [
        "field completeness below threshold",
        "identifier ambiguity"
      ]
    },
    {
      "status": "ready_for_trusted_candidate",
      "conditions": [
        "coverage, freshness, field, cross-source and license/storage blockers cleared"
      ],
      "evidence_required": [
        "coverage report",
        "freshness report",
        "field report",
        "license/storage boundary"
      ],
      "downgrade_conditions": [
        "any major blocker reappears"
      ]
    },
    {
      "status": "trusted_candidate",
      "conditions": [
        "ready_for_trusted evidence complete",
        "still not formal trusted consumption"
      ],
      "evidence_required": [
        "approval-ready audit trail",
        "QA passed",
        "source usage boundary"
      ],
      "downgrade_conditions": [
        "license conflict",
        "quality regression",
        "cross-source regression"
      ]
    },
    {
      "status": "blocked",
      "conditions": [
        "cannot proceed without user action, permission, official benchmark, or schema clarity"
      ],
      "evidence_required": [
        "blocker reason",
        "next action"
      ],
      "downgrade_conditions": []
    }
  ],
  "formal_trusted_consumption_unchanged": true
}