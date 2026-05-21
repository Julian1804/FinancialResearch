# Trust Closure Readiness Rules v4

Generated: 2026-05-21T06:03:42Z

- `candidate`: source is reachable/cached, source role classified
- `schema_validated_candidate`: required schema fields present, dates parse, units/currency classified, checksum exists, QA is not failed
- `cross_validated_candidate`: two independent non-identical sources match core fields, mismatches explainable or queued
- `freshness_validated_candidate`: latest observation fits expected cadence, retrieval cadence tracked, next expected update exists or is bounded
- `field_validated_candidate`: critical identifiers/date/value fields complete above threshold, field definitions clear
- `licensed_high_confidence_candidate`: licensed institutional platform, entitlement allowed, sample/metadata fields support FR use, token handled manually
- `historical_identifier_anchor`: strong identifier fields available even if freshness is insufficient, useful for Entity Master crosswalk
- `ready_for_trusted_candidate`: schema, cross-source, freshness, release calendar, coverage, entity mapping, and license/storage blockers closed
- `trusted_candidate`: ready_for_trusted evidence complete, formal trusted consumption still unchanged
- `blocked`: requires user action, entitlement, official benchmark, or safe source clarity

Morningstar is treated as a licensed institutional data platform, not as a public free source and not as a blanket trusted source.
