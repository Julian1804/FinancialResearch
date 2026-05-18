# Connector Framework Design

## Pipeline

All Phase 2 connectors follow:

raw data preservation -> source classification -> parsing/extraction -> normalization -> quality checks -> trust resolution -> consumption eligibility.

## Config Sources

- `config/storage_paths.json`
- `runtime/data_connector_feasibility/source_registry.json`

## Result Schema

Each connector result includes:

- `source_id`
- `source_name`
- `connector_name`
- `provider_type`
- `official_source`
- `trusted_external_eligible`
- `retrieved_at`
- `source_url_or_reference`
- `raw_output_path`
- `normalized_output_path`
- `quality_check_status`
- `trust_status`
- `candidate_only`
- `error_message`

## Metadata Index

SQLite prototype tables:

- `source_registry_index`
- `connector_run_log`
- `normalized_dataset_index`
- `quality_check_log`
