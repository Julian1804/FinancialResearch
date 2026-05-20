# Macro Asset Quality Gate

Generated: 2026-05-20T06:48:52Z

Checks:

- required fields present
- value numeric
- date parseable
- duplicate series_id + observation_date
- frequency consistency
- extreme outlier detection
- missing value ratio
- unit present
- currency present for commodity price series
- source_id present
- raw checksum present
- publish_date status classified
- revision/vintage status classified

Quality counts:

```json
{
  "quality_passed": 40,
  "quality_warning": 1
}
```

Official/authoritative sources with quality_passed are still only `trusted_by_real_external_candidate`; this phase does not enter formal trusted consumption.
