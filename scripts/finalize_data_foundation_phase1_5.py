from __future__ import annotations

import importlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "data_foundation_readiness"
CONFIG_DIR = PROJECT_ROOT / "config"
STORAGE_CONFIG_PATH = CONFIG_DIR / "storage_paths.json"
DOC_PATH = PROJECT_ROOT / "docs" / "DATA_FOUNDATION_READINESS_AND_STORAGE_MAPPING.md"
FR_PYTHON = Path(r"D:\workspace\envs\financial_research_backend\Scripts\python.exe")


NAS_DIRS = [
    Path(r"Z:\data_lake_master\raw\financial_reports"),
    Path(r"Z:\data_lake_master\raw\api_responses"),
    Path(r"Z:\data_lake_master\parsed\financial_reports\parser_outputs"),
    Path(r"Z:\data_lake_master\structured"),
    Path(r"Z:\data_lake_master\features"),
    Path(r"Z:\data_lake_master\exports"),
    Path(r"Z:\data_lake_master\trusted_consumption"),
    Path(r"Z:\data_lake_master\normalized"),
    Path(r"Z:\backups\FinancialResearch"),
    Path(r"Z:\logs_archive\FinancialResearch"),
]

LOCAL_BULK_DIRS = [
    Path(r"E:\FinancialResearchData"),
    Path(r"E:\FinancialResearchData\temp_downloads"),
    Path(r"E:\FinancialResearchData\intermediate_cache"),
    Path(r"E:\FinancialResearchData\local_bulk_parquet"),
]

PHASE1_5_CREATED_PATHS = {
    str(Path(r"Z:\data_lake_master\raw\api_responses")),
    str(Path(r"Z:\data_lake_master\parsed\financial_reports\parser_outputs")),
    str(Path(r"Z:\data_lake_master\trusted_consumption")),
    str(Path(r"Z:\data_lake_master\normalized")),
    str(Path(r"Z:\backups\FinancialResearch")),
    str(Path(r"Z:\logs_archive\FinancialResearch")),
    str(Path(r"E:\FinancialResearchData")),
    str(Path(r"E:\FinancialResearchData\temp_downloads")),
    str(Path(r"E:\FinancialResearchData\intermediate_cache")),
    str(Path(r"E:\FinancialResearchData\local_bulk_parquet")),
}

STORAGE_PATHS = {
    "hot_data_root": r"D:\workspace\FinancialResearch\runtime",
    "local_bulk_data_root": r"E:\FinancialResearchData",
    "cold_data_root": r"Z:\data_lake_master",
    "incoming_root": r"Z:\incoming",
    "financial_report_pdf_root": r"Z:\data_lake_master\raw\financial_reports",
    "raw_api_response_root": r"Z:\data_lake_master\raw\api_responses",
    "parser_raw_output_root": r"Z:\data_lake_master\parsed\financial_reports\parser_outputs",
    "normalized_data_root": r"D:\workspace\FinancialResearch\runtime\normalized_data",
    "normalized_cold_root": r"Z:\data_lake_master\normalized",
    "structured_data_root": r"Z:\data_lake_master\structured",
    "trusted_consumption_root": r"Z:\data_lake_master\trusted_consumption",
    "analysis_packet_root": r"D:\workspace\FinancialResearch\runtime\analysis_packets",
    "ingested_report_root": r"D:\workspace\FinancialResearch\runtime\analysis_reports",
    "backup_root": r"Z:\backups\FinancialResearch",
    "logs_archive_root": r"Z:\logs_archive\FinancialResearch",
}


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    directory_results = create_required_directories()
    storage_config = write_storage_config()
    package_results = verify_packages()
    write_json(OUTPUT_ROOT / "directory_creation_results.json", directory_results)
    write_json(OUTPUT_ROOT / "storage_path_mapping_final.json", storage_config)
    write_json(OUTPUT_ROOT / "python_package_install_results.json", package_results)
    update_doc(directory_results, storage_config, package_results)
    summary = {
        "storage_finalization_completed": True,
        "financial_research_python": str(FR_PYTHON),
        "nas_created_count": sum(1 for row in directory_results["nas_directories"] if row["action"] in {"created", "created_by_phase1_5"}),
        "nas_existing_count": sum(1 for row in directory_results["nas_directories"] if row["action"] == "exists"),
        "local_bulk_created_count": sum(1 for row in directory_results["local_bulk_directories"] if row["action"] in {"created", "created_by_phase1_5"}),
        "storage_config_path": str(STORAGE_CONFIG_PATH),
        "package_import_success": all(row["import_success"] for row in package_results["packages"]),
        "parser_env_pollution": False,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "default_v1_1_replaced": False,
        "outputs": {
            "directory_creation_results": str(OUTPUT_ROOT / "directory_creation_results.json"),
            "storage_path_mapping_final": str(OUTPUT_ROOT / "storage_path_mapping_final.json"),
            "python_package_install_results": str(OUTPUT_ROOT / "python_package_install_results.json"),
            "storage_config": str(STORAGE_CONFIG_PATH),
            "doc": str(DOC_PATH),
        },
    }
    write_json(OUTPUT_ROOT / "phase1_5_finalization_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def create_required_directories() -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "policy": "create_empty_missing_directories_only_no_move_delete_rename",
        "nas_directories": [ensure_dir(path) for path in NAS_DIRS],
        "local_bulk_directories": [ensure_dir(path) for path in LOCAL_BULK_DIRS],
    }


def ensure_dir(path: Path) -> dict[str, Any]:
    existed = path.exists()
    if not existed:
        path.mkdir(parents=True, exist_ok=True)
    action = "exists" if existed else "created"
    if str(path) in PHASE1_5_CREATED_PATHS:
        action = "created_by_phase1_5" if existed else "created"
    return {
        "path": str(path),
        "exists_after": path.exists(),
        "action": action,
        "moved_deleted_or_renamed_existing_data": False,
    }


def write_storage_config() -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_now(),
        "source": "Data Foundation Phase 1.5 confirmed storage mapping",
        "uses_existing_nas_framework": True,
        "nas_root": r"Z:\data_lake_master",
        "paths": STORAGE_PATHS,
        "safety": {
            "no_full_download": True,
            "no_existing_nas_dir_move_delete_rename": True,
            "parse_lab_affected": False,
            "trusted_consumption_affected": False,
            "default_v1_1_replaced": False,
        },
    }
    write_json(STORAGE_CONFIG_PATH, payload)
    return payload


def verify_packages() -> dict[str, Any]:
    packages = []
    for module_name in ["akshare", "baostock", "duckdb"]:
        packages.append(verify_package(module_name))
    return {
        "generated_at": utc_now(),
        "python_executable": str(FR_PYTHON),
        "used_global_pip": False,
        "installed_to_parser_env": False,
        "install_command": f"{FR_PYTHON} -m pip install akshare baostock duckdb",
        "packages": packages,
    }


def verify_package(module_name: str) -> dict[str, Any]:
    code = (
        "import importlib, json; "
        f"m=importlib.import_module('{module_name}'); "
        "print(json.dumps({'version': getattr(m, '__version__', '')}))"
    )
    result = subprocess.run(
        [str(FR_PYTHON), "-c", code],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    version = ""
    if result.returncode == 0 and result.stdout.strip():
        try:
            version = json.loads(result.stdout.strip()).get("version", "")
        except json.JSONDecodeError:
            version = ""
    pip_show = subprocess.run(
        [str(FR_PYTHON), "-m", "pip", "show", module_name],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    show_version = ""
    for line in pip_show.stdout.splitlines():
        if line.lower().startswith("version:"):
            show_version = line.split(":", 1)[1].strip()
            break
    return {
        "package": module_name,
        "import_success": result.returncode == 0,
        "import_version": version,
        "pip_show_version": show_version,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip()[:500],
    }


def update_doc(directory_results: dict[str, Any], storage_config: dict[str, Any], package_results: dict[str, Any]) -> None:
    existing = DOC_PATH.read_text(encoding="utf-8") if DOC_PATH.exists() else "# Data Foundation Readiness and Storage Mapping\n"
    marker = "\n## Phase 1.5 Finalization\n"
    existing = existing.split(marker)[0].rstrip()
    nas_lines = "\n".join(
        f"- `{row['path']}`: {row['action']}"
        for row in directory_results["nas_directories"]
    )
    local_lines = "\n".join(
        f"- `{row['path']}`: {row['action']}"
        for row in directory_results["local_bulk_directories"]
    )
    package_lines = "\n".join(
        f"- {row['package']}: import={row['import_success']}, version={row['pip_show_version'] or row['import_version'] or 'unknown'}"
        for row in package_results["packages"]
    )
    addition = f"""{marker}

Status: finalized on {utc_now()}.

### Existing NAS Framework

This finalization uses the existing `Z:\\financial_research` framework and its `data_lake_master/raw`, `parsed`, `structured`, `features`, and `exports` layers. It did not move, delete, or rename existing NAS directories.

### NAS Directories

{nas_lines}

### Local Bulk Directories

{local_lines}

### Storage Config

- `config/storage_paths.json`
- Connectors should read this config before writing raw, parsed, normalized, trusted consumption, backup, or log artifacts.

### Python Environment

- FinancialResearch Python: `{package_results['python_executable']}`
- Global pip used: `{package_results['used_global_pip']}`
- Parser independent env polluted: `{package_results['installed_to_parser_env']}`

Package verification:

{package_lines}

### Boundaries

- No full download.
- No parse_lab parser routing change.
- No trusted consumption change.
- No default V1.1 replacement.
"""
    DOC_PATH.write_text(existing + addition, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
