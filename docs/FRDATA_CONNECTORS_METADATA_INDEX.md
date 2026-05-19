# FRDataConnectors Metadata Index

Metadata DB: `D:\workspace\FinancialResearch\runtime\frdata_connectors_phase6\frdata_connectors_metadata.sqlite`

NAS backup: `Z:\data_lake_master\structured\metadata_index_backups\frdata_connectors_phase6_metadata.sqlite`

## Tables

```json
{
  "connector_run_log": 9,
  "dataset_index": 9,
  "raw_artifact_index": 7,
  "normalized_dataset_index": 9,
  "quality_check_log": 11,
  "trust_status_log": 9,
  "staging_dataset_index": 11,
  "source_status_index": 8
}
```

## Traceability

Every raw, normalized, quality, trust, and staging record has run_id/source_id linkage.

The index is a prototype metadata layer. It does not replace the existing trusted consumption layer.
