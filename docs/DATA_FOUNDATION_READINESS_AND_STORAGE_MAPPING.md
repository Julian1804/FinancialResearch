# Data Foundation Readiness and Storage Mapping

## Hardware / NAS Facts

- Desktop: Julian-BASE, Windows 11 Pro 25H2 64-bit, Intel Core i7-9700K, 64GB RAM, GTX 1070 8GB.
- Local disks: C: KINGSTON SSD, D: SN570 SSD, E: Seagate HDD.
- NAS: NASTS464C2C / QNAP TS-464C2 / 192.168.0.103 / 32GB RAM / DataVol1 about 5.63TB with about 4.54TB free.
- Preferred NAS share: `Z:` -> `\\192.168.0.103\financial_research`.
- `P:` is Public and is not the preferred FinancialResearch root.

## Legacy Storage Framework Discovery

Targeted search was run against FinancialResearch docs/runtime/config/project root, parse_lab docs/runtime/project root, and selected `Z:` directories only. No full NAS deep scan was performed.

| File | Summary | Use for mapping | Conflict |
|---|---|---:|---|
| `\\192.168.0.103\financial_research\@Recycle\01_CREATE_NAS_FINANCIAL_RESEARCH_STRUCTURE.ps1` | Old NAS financial_research directory creation script defining data_lake_master/incoming/backups/logs/release/contracts layers. | True | none_detected |
| `\\192.168.0.103\financial_research\@Recycle\01_CREATE_NAS_FINANCIAL_RESEARCH_STRUCTURE.ps1[1]` | Old NAS financial_research directory creation script defining data_lake_master/incoming/backups/logs/release/contracts layers. | True | none_detected |
| `D:\workspace\FinancialResearch\docs\DATA_STORAGE_ARCHITECTURE.md` | Phase 1 data storage architecture doc. | True | none_detected |
| `D:\workspace\FinancialResearch\docs\DATA_CONNECTOR_FEASIBILITY_AUDIT.md` | Phase 1 connector/source registry doc. | True | none_detected |
| `D:\workspace\FinancialResearch\docs\DATA_SOURCE_REGISTRY_SCHEMA.md` | Phase 1 connector/source registry doc. | True | none_detected |
| `D:\workspace\FinancialResearch\docs\FINANCIAL_RESEARCH_NEW_ARCHITECTURE.md` | Existing architecture doc mentioning optional NAS_ROOT. | True | none_detected |
| `D:\workspace\FinancialResearch\docs\LOCAL_PROJECT_INVENTORY.md` | - If QNAP settings are enabled, data root can be under a NAS mount. | True | none_detected |
| `D:\workspace\parse_lab\config\env_paths.json` | "nas_root": "\\\\192.168.0.103\\financial_research" | True | none_detected |

Decision: `use_existing_nas_framework_as_primary_mapping_source`.

## Existing NAS Folder Interpretation

| Path | Intended use | Evidence |
|---|---|---|
| `Z:/data_lake_master` | FR data lake master root | confirmed_from_old_file |
| `Z:/incoming` | external/manual download landing zone | confirmed_from_old_file |
| `Z:/backups` | backup root | confirmed_from_old_file |
| `Z:/logs_archive` | long-term log archive | confirmed_from_old_file |
| `Z:/module_archives` | module archive root | confirmed_from_old_file |
| `Z:/release_artifacts` | release/build artifact root | confirmed_from_old_file |
| `Z:/shared_contracts_backup` | shared contract/schema/API backup root | confirmed_from_old_file |
| `Z:/snapshots_note` | snapshot notes and restore runbook area | confirmed_from_old_file |
| `Z:/@Recently-Snapshot` | QNAP system snapshot area, not business data | confirmed_system_folder |
| `Z:/@Recycle` | QNAP recycle area, not business data; old script found here only as evidence | confirmed_system_folder |

`Z:/@Recently-Snapshot` and `Z:/@Recycle` are QNAP system directories and are not business data directories.

## Path Validation

| Drive | Exists | Total | Free |
|---|---:|---:|---:|
| C: | True | 222.47 GB | 95.43 GB |
| D: | True | 931.50 GB | 872.75 GB |
| E: | True | 1.82 TB | 1.75 TB |
| P: | True | 5.63 TB | 4.54 TB |
| Z: | True | 5.63 TB | 4.54 TB |

- `D:/workspace` exists.
- `D:/workspace/FinancialResearch` size: 7.37 MB.
- `D:/workspace/parse_lab` size: 287.98 MB.
- `D:/workspace/runtime` size: 3.53 GB.
- Z readable: True.
- Z writable small temp test: True.

## Storage Path Mapping Draft

| Path ID | Path | Tier | Purpose | Evidence |
|---|---|---|---|---|
| `hot_data_root` | `D:/workspace/FinancialResearch/runtime` | local | current development, DuckDB/SQLite, recent Parquet, small cache, packets, reports | confirmed_from_project_layout |
| `local_bulk_data_root` | `E:/FinancialResearchData` | local | medium-term cache and larger local working files; create only after user confirms | user_confirmation_needed |
| `cold_data_root` | `Z:/data_lake_master` | nas | FR data lake master root from old NAS framework | confirmed_from_old_file |
| `incoming_root` | `Z:/incoming` | nas | manual imports, temporary download landing zone, unprocessed external data | confirmed_from_old_file |
| `financial_report_pdf_root` | `Z:/data_lake_master/raw/financial_reports` | nas | PDF originals for financial reports | confirmed_from_old_file |
| `parser_raw_output_root` | `Z:/data_lake_master/parsed/financial_reports/parser_outputs` | nas | candidate parser raw output archive; subfolder is draft below old parsed/financial_reports | user_confirmation_needed |
| `raw_api_response_root_hot` | `D:/workspace/FinancialResearch/runtime/raw_api_responses` | local | short-term raw API response cache | draft_local_hot_path |
| `raw_api_response_root_cold` | `Z:/data_lake_master/raw/market_data/api_responses` | nas | long-term raw API response archive under old raw/market_data | user_confirmation_needed |
| `normalized_data_root_hot` | `D:/workspace/FinancialResearch/runtime/normalized_data` | local | hot normalized Parquet/DuckDB outputs | draft_local_hot_path |
| `normalized_data_root_cold` | `Z:/data_lake_master/structured` | nas | normalized durable data using old structured layer | confirmed_from_old_file |
| `trusted_consumption_data_root_hot` | `D:/workspace/FinancialResearch/runtime/trusted_consumption` | local | hot trusted consumption payloads | draft_local_hot_path |
| `trusted_consumption_data_root_cold` | `Z:/data_lake_master/structured/trusted_consumption` | nas | trusted consumption backups; draft subfolder under old structured layer | user_confirmation_needed |
| `analysis_packet_root` | `D:/workspace/FinancialResearch/runtime/analysis_packets` | local | human-in-the-loop GPT packet output | draft_local_hot_path |
| `ingested_report_root` | `D:/workspace/FinancialResearch/runtime/analysis_reports` | local | ingested GPT Web reports and report versions | draft_local_hot_path |
| `backup_root` | `Z:/backups` | nas | backup root from old NAS framework | confirmed_from_old_file |
| `logs_archive_root` | `Z:/logs_archive` | nas | long-term logs archive from old NAS framework | confirmed_from_old_file |
| `release_artifacts_root` | `Z:/release_artifacts` | nas | release/build artifacts from old NAS framework | confirmed_from_old_file |
| `shared_contracts_backup_root` | `Z:/shared_contracts_backup` | nas | schema/API/shared contract backups from old NAS framework | confirmed_from_old_file |

This mapping aligns the new FR data foundation with the old NAS framework:

- raw source files map to `data_lake_master/raw`.
- parser-derived files map to `data_lake_master/parsed`.
- normalized consumption data maps to `data_lake_master/structured`.
- features and exports keep their existing framework locations.
- backups/logs/releases/contracts use the existing top-level NAS directories.

## Data Source Setup Checklist

| Package | Installed | Command |
|---|---:|---|
| akshare | False | `python -m pip install akshare` |
| baostock | False | `python -m pip install baostock` |
| duckdb | False | `python -m pip install duckdb` |
| pyarrow | True | `python -m pip install pyarrow` |
| pandas | True | `python -m pip install pandas` |
| requests | True | `python -m pip install requests` |

## API Key / Account Notes

- No key needed for current BLS / Treasury / SEC / World Bank / CNINFO small smoke.
- EIA likely needs API key or key-policy confirmation before connector work.
- Wind / Morningstar need licensed access and are not Phase 1 mainline.
- Eastmoney / Tonghuashun need official or authorized endpoints before trusted use.
- FRED timed out in Phase 1 smoke; retry or alternate download method needed.

## Safety

- No large download was started.
- No NAS folder was moved, deleted, or renamed.
- Only one small Z write-test file was created and deleted.
- parse_lab and trusted consumption were not changed.
## Phase 1.5 Finalization


Status: finalized on 2026-05-18T11:12:58Z.

### Existing NAS Framework

This finalization uses the existing `Z:\financial_research` framework and its `data_lake_master/raw`, `parsed`, `structured`, `features`, and `exports` layers. It did not move, delete, or rename existing NAS directories.

### NAS Directories

- `Z:\data_lake_master\raw\financial_reports`: exists
- `Z:\data_lake_master\raw\api_responses`: created_by_phase1_5
- `Z:\data_lake_master\parsed\financial_reports\parser_outputs`: created_by_phase1_5
- `Z:\data_lake_master\structured`: exists
- `Z:\data_lake_master\features`: exists
- `Z:\data_lake_master\exports`: exists
- `Z:\data_lake_master\trusted_consumption`: created_by_phase1_5
- `Z:\data_lake_master\normalized`: created_by_phase1_5
- `Z:\backups\FinancialResearch`: created_by_phase1_5
- `Z:\logs_archive\FinancialResearch`: created_by_phase1_5

### Local Bulk Directories

- `E:\FinancialResearchData`: created_by_phase1_5
- `E:\FinancialResearchData\temp_downloads`: created_by_phase1_5
- `E:\FinancialResearchData\intermediate_cache`: created_by_phase1_5
- `E:\FinancialResearchData\local_bulk_parquet`: created_by_phase1_5

### Storage Config

- `config/storage_paths.json`
- Connectors should read this config before writing raw, parsed, normalized, trusted consumption, backup, or log artifacts.

### Python Environment

- FinancialResearch Python: `D:\workspace\envs\financial_research_backend\Scripts\python.exe`
- Global pip used: `False`
- Parser independent env polluted: `False`

Package verification:

- akshare: import=True, version=1.18.62
- baostock: import=True, version=0.9.1
- duckdb: import=True, version=1.5.2

### Boundaries

- No full download.
- No parse_lab parser routing change.
- No trusted consumption change.
- No default V1.1 replacement.
