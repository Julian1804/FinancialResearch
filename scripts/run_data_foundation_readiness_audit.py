from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "data_foundation_readiness"
DOC_PATH = PROJECT_ROOT / "docs" / "DATA_FOUNDATION_READINESS_AND_STORAGE_MAPPING.md"

NAS_ROOT = Path("Z:/")
PUBLIC_ROOT = Path("P:/")

KEYWORDS = [
    "storage",
    "STORAGE",
    "data_lake",
    "DATA_LAKE",
    "nas",
    "NAS",
    "path_mapping",
    "storage_mapping",
    "data_foundation",
    "data_storage",
    "DATA_STORAGE",
    "financial_research",
    "hot_data",
    "cold_data",
    "raw",
    "normalized",
    "trusted",
    "consumption",
    "backup",
    "archive",
]

TARGET_SEARCH_ROOTS = [
    PROJECT_ROOT / "docs",
    PROJECT_ROOT / "runtime",
    PROJECT_ROOT / "config",
    PROJECT_ROOT,
    Path("D:/workspace/parse_lab/docs"),
    Path("D:/workspace/parse_lab/runtime"),
    Path("D:/workspace/parse_lab"),
    NAS_ROOT,
    NAS_ROOT / "data_lake_master",
    NAS_ROOT / "incoming",
    NAS_ROOT / "backups",
    NAS_ROOT / "snapshots_note",
    NAS_ROOT / "shared_contracts_backup",
]


def main() -> int:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    discovery = discover_legacy_storage_framework()
    inventory = build_local_storage_inventory()
    mapping = build_storage_mapping_draft(discovery, inventory)
    checklist = build_data_source_setup_checklist()
    user_actions = build_user_action_required(discovery, inventory, mapping, checklist)
    write_json(OUTPUT_ROOT / "legacy_storage_framework_discovery.json", discovery)
    write_json(OUTPUT_ROOT / "local_storage_inventory.json", inventory)
    write_json(OUTPUT_ROOT / "storage_path_mapping_draft.json", mapping)
    write_json(OUTPUT_ROOT / "data_source_setup_checklist.json", checklist)
    (OUTPUT_ROOT / "user_action_required.md").write_text(user_actions, encoding="utf-8")
    DOC_PATH.write_text(render_doc(discovery, inventory, mapping, checklist), encoding="utf-8")
    summary = {
        "readiness_audit_completed": True,
        "legacy_storage_framework_found": bool(discovery["legacy_framework_candidates"]),
        "z_readable": inventory["nas_validation"]["Z"]["exists"],
        "z_writable": inventory["nas_validation"]["Z"]["write_test"]["success"],
        "outputs": {
            "legacy_storage_framework_discovery": str(OUTPUT_ROOT / "legacy_storage_framework_discovery.json"),
            "local_storage_inventory": str(OUTPUT_ROOT / "local_storage_inventory.json"),
            "storage_path_mapping_draft": str(OUTPUT_ROOT / "storage_path_mapping_draft.json"),
            "data_source_setup_checklist": str(OUTPUT_ROOT / "data_source_setup_checklist.json"),
            "user_action_required": str(OUTPUT_ROOT / "user_action_required.md"),
            "doc": str(DOC_PATH),
        },
    }
    write_json(OUTPUT_ROOT / "data_foundation_readiness_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def discover_legacy_storage_framework() -> dict[str, Any]:
    files = []
    seen: set[str] = set()
    for root in TARGET_SEARCH_ROOTS:
        if not root.exists():
            continue
        max_depth = 2 if str(root).upper().startswith("Z:") else 4
        for path in walk_files_limited(root, max_depth=max_depth):
            if is_generated_readiness_output(path):
                continue
            if str(path) in seen or path.stat().st_size > 5_000_000:
                continue
            seen.add(str(path))
            name_hit = any(keyword.lower() in path.name.lower() for keyword in KEYWORDS)
            content_hits = scan_content_hits(path)
            if not name_hit and not content_hits:
                continue
            files.append(
                {
                    "path": str(path),
                    "size_bytes": path.stat().st_size,
                    "name_hit": name_hit,
                    "content_hit": bool(content_hits),
                    "sample_hits": content_hits[:5],
                    "summary": summarize_legacy_file(path, content_hits),
                    "should_inform_storage_mapping": should_inform_storage_mapping(path, content_hits),
                    "conflict": infer_conflict(path, content_hits),
                }
            )
    framework_candidates = [
        item
        for item in files
        if item["should_inform_storage_mapping"]
        or Path(item["path"]).name.lower().startswith("01_create_nas_financial_research_structure")
    ]
    framework_candidates.sort(key=legacy_candidate_sort_key)
    return {
        "generated_at": utc_now(),
        "search_scope": [str(path) for path in TARGET_SEARCH_ROOTS],
        "keywords": KEYWORDS,
        "found_file_count": len(files),
        "legacy_framework_candidates": framework_candidates,
        "all_hits": files,
        "decision": "use_existing_nas_framework_as_primary_mapping_source" if framework_candidates else "fallback_to_current_z_folder_names",
    }


def build_local_storage_inventory() -> dict[str, Any]:
    drives = {}
    for letter in ["C", "D", "E", "P", "Z"]:
        path = Path(f"{letter}:/")
        drives[letter] = drive_info(path)
    paths = {
        "workspace": Path("D:/workspace"),
        "FinancialResearch": PROJECT_ROOT,
        "parse_lab": Path("D:/workspace/parse_lab"),
        "workspace_runtime": Path("D:/workspace/runtime"),
    }
    project_sizes = {
        key: {
            "path": str(path),
            "exists": path.exists(),
            "size_bytes": safe_dir_size(path) if path.exists() else 0,
            "size_human": human_size(safe_dir_size(path)) if path.exists() else "missing",
        }
        for key, path in paths.items()
    }
    nas_validation = {
        "P": {
            "path": str(PUBLIC_ROOT),
            "exists": PUBLIC_ROOT.exists(),
            "role": "public_share_not_preferred_for_financialresearch",
        },
        "Z": {
            "path": str(NAS_ROOT),
            "exists": NAS_ROOT.exists(),
            "readable": is_readable(NAS_ROOT),
            "write_test": z_write_test(),
            "role": "preferred_financialresearch_nas_root",
            "top_level_dirs": list_top_level(NAS_ROOT),
        },
    }
    return {
        "generated_at": utc_now(),
        "provided_hardware_facts": {
            "desktop": {
                "device_name": "Julian-BASE",
                "os": "Windows 11 Pro 25H2 64-bit",
                "cpu": "Intel Core i7-9700K @ 3.60GHz",
                "ram": "64GB",
                "gpu": "NVIDIA GeForce GTX 1070 8GB",
                "total_storage": "about 2.95TB",
                "used_storage": "about 256GB",
            },
            "nas": {
                "name": "NASTS464C2C",
                "model": "QNAP TS-464C2",
                "ip": "192.168.0.103",
                "cpu": "Intel Celeron N5095 4C/4T",
                "ram": "32GB",
                "datavol1_capacity": "about 5.63TB",
                "datavol1_free": "about 4.54TB",
                "public_mapping": "P: -> \\\\192.168.0.103\\Public",
                "financial_research_mapping": "Z: -> \\\\192.168.0.103\\financial_research",
            },
        },
        "drive_validation": drives,
        "project_sizes": project_sizes,
        "nas_validation": nas_validation,
    }


def build_storage_mapping_draft(discovery: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    old_framework_source = (
        discovery["legacy_framework_candidates"][0]["path"]
        if discovery["legacy_framework_candidates"]
        else "current_z_folder_structure"
    )
    mappings = [
        mapping("hot_data_root", "D:/workspace/FinancialResearch/runtime", "local", "current development, DuckDB/SQLite, recent Parquet, small cache, packets, reports", "confirmed_from_project_layout"),
        mapping("local_bulk_data_root", "E:/FinancialResearchData", "local", "medium-term cache and larger local working files; create only after user confirms", "user_confirmation_needed", exists=False),
        mapping("cold_data_root", "Z:/data_lake_master", "nas", "FR data lake master root from old NAS framework", "confirmed_from_old_file"),
        mapping("incoming_root", "Z:/incoming", "nas", "manual imports, temporary download landing zone, unprocessed external data", "confirmed_from_old_file"),
        mapping("financial_report_pdf_root", "Z:/data_lake_master/raw/financial_reports", "nas", "PDF originals for financial reports", "confirmed_from_old_file"),
        mapping("parser_raw_output_root", "Z:/data_lake_master/parsed/financial_reports/parser_outputs", "nas", "candidate parser raw output archive; subfolder is draft below old parsed/financial_reports", "user_confirmation_needed", exists=False),
        mapping("raw_api_response_root_hot", "D:/workspace/FinancialResearch/runtime/raw_api_responses", "local", "short-term raw API response cache", "draft_local_hot_path", exists=False),
        mapping("raw_api_response_root_cold", "Z:/data_lake_master/raw/market_data/api_responses", "nas", "long-term raw API response archive under old raw/market_data", "user_confirmation_needed", exists=False),
        mapping("normalized_data_root_hot", "D:/workspace/FinancialResearch/runtime/normalized_data", "local", "hot normalized Parquet/DuckDB outputs", "draft_local_hot_path", exists=False),
        mapping("normalized_data_root_cold", "Z:/data_lake_master/structured", "nas", "normalized durable data using old structured layer", "confirmed_from_old_file"),
        mapping("trusted_consumption_data_root_hot", "D:/workspace/FinancialResearch/runtime/trusted_consumption", "local", "hot trusted consumption payloads", "draft_local_hot_path", exists=False),
        mapping("trusted_consumption_data_root_cold", "Z:/data_lake_master/structured/trusted_consumption", "nas", "trusted consumption backups; draft subfolder under old structured layer", "user_confirmation_needed", exists=False),
        mapping("analysis_packet_root", "D:/workspace/FinancialResearch/runtime/analysis_packets", "local", "human-in-the-loop GPT packet output", "draft_local_hot_path", exists=False),
        mapping("ingested_report_root", "D:/workspace/FinancialResearch/runtime/analysis_reports", "local", "ingested GPT Web reports and report versions", "draft_local_hot_path", exists=False),
        mapping("backup_root", "Z:/backups", "nas", "backup root from old NAS framework", "confirmed_from_old_file"),
        mapping("logs_archive_root", "Z:/logs_archive", "nas", "long-term logs archive from old NAS framework", "confirmed_from_old_file"),
        mapping("release_artifacts_root", "Z:/release_artifacts", "nas", "release/build artifacts from old NAS framework", "confirmed_from_old_file"),
        mapping("shared_contracts_backup_root", "Z:/shared_contracts_backup", "nas", "schema/API/shared contract backups from old NAS framework", "confirmed_from_old_file"),
    ]
    for item in mappings:
        item["exists"] = Path(item["path"]).exists() if item["exists"] is None else item["exists"]
    return {
        "generated_at": utc_now(),
        "old_framework_source": old_framework_source,
        "mapping_policy": "align_new_data_foundation_to_existing_z_financial_research_framework",
        "do_not_use_as_business_dirs": ["Z:/@Recently-Snapshot", "Z:/@Recycle"],
        "mappings": mappings,
        "nas_folder_interpretation": nas_folder_interpretation(discovery),
    }


def build_data_source_setup_checklist() -> dict[str, Any]:
    packages = {
        name: {
            "installed": importlib.util.find_spec(name) is not None,
            "install_command": f"python -m pip install {name}",
        }
        for name in ["akshare", "baostock", "duckdb", "pyarrow", "pandas", "requests"]
    }
    return {
        "generated_at": utc_now(),
        "python_packages": packages,
        "data_sources": {
            "AKShare": {
                "status": "install_then_test" if not packages["akshare"]["installed"] else "installed_ready_for_small_test",
                "requires_api_key": False,
                "requires_account": False,
                "trusted_policy": "only official-upstream datasets can become trusted_by_real_external",
            },
            "Baostock": {
                "status": "install_then_test" if not packages["baostock"]["installed"] else "installed_ready_for_small_test",
                "requires_api_key": False,
                "requires_account": False,
                "trusted_policy": "candidate until upstream provenance is documented",
            },
            "DuckDB": {"status": "install_recommended" if not packages["duckdb"]["installed"] else "installed"},
            "pyarrow": {"status": "install_recommended" if not packages["pyarrow"]["installed"] else "installed"},
            "pandas": {"status": "install_recommended" if not packages["pandas"]["installed"] else "installed"},
            "requests": {"status": "install_recommended" if not packages["requests"]["installed"] else "installed"},
            "EIA": {"requires_api_key": True, "status": "defer_until_api_key_policy_confirmed"},
            "FRED": {"requires_api_key": False, "status": "retry_or_switch_download_method_after_timeout"},
            "BLS": {"requires_api_key": False, "status": "small_smoke_passed"},
            "Treasury FiscalData": {"requires_api_key": False, "status": "small_smoke_passed"},
            "SEC": {"requires_api_key": False, "status": "small_smoke_passed"},
            "World Bank": {"requires_api_key": False, "status": "small_smoke_passed"},
            "CNINFO": {"requires_api_key": False, "status": "small_smoke_passed_rate_terms_review_needed"},
            "Wind": {"requires_account": True, "requires_api_key": True, "requires_paid_or_license": True, "status": "defer_paid_source"},
            "Morningstar": {"requires_account": True, "requires_api_key": True, "requires_paid_or_license": True, "status": "defer_paid_or_authorized_source"},
            "Eastmoney": {"requires_account": "maybe", "terms_risk": "medium", "status": "do_not_trust_without_official_or_authorized_endpoint"},
            "Tonghuashun": {"requires_account": "maybe", "terms_risk": "medium", "status": "do_not_trust_without_official_or_authorized_endpoint"},
        },
        "install_commands": [
            "python -m pip install duckdb pyarrow pandas requests",
            "python -m pip install akshare baostock",
        ],
        "no_packages_installed_by_this_audit": True,
    }


def build_user_action_required(discovery: dict[str, Any], inventory: dict[str, Any], mapping_doc: dict[str, Any], checklist: dict[str, Any]) -> str:
    needed_packages = [
        name
        for name, info in checklist["python_packages"].items()
        if not info["installed"]
    ]
    confirm_paths = [
        item["path_id"]
        for item in mapping_doc["mappings"]
        if item["evidence_status"] == "user_confirmation_needed"
    ]
    return "\n".join(
        [
            "# User Action Required",
            "",
            "## Confirm Storage Mapping",
            "",
            "- Confirm that `Z:/data_lake_master` should remain the cold data lake root.",
            "- Confirm whether draft subfolders under existing old layers may be created later.",
            *[f"- Confirm mapping: `{item}`" for item in confirm_paths],
            "",
            "## Optional Python Packages",
            "",
            *[f"- {name}: `{checklist['python_packages'][name]['install_command']}`" for name in needed_packages],
            "",
            "## Data Source Accounts / Keys",
            "",
            "- EIA: confirm whether to request/use an API key.",
            "- Wind / Morningstar: only if you already have licensed access.",
            "- Eastmoney / Tonghuashun: confirm official or authorized API before treating as trusted.",
            "",
            "## NAS",
            "",
            f"- Z write test success: {inventory['nas_validation']['Z']['write_test']['success']}",
            "- Do not move/delete existing NAS directories; this audit did not do so.",
            "",
        ]
    )


def render_doc(discovery: dict[str, Any], inventory: dict[str, Any], mapping_doc: dict[str, Any], checklist: dict[str, Any]) -> str:
    legacy_rows = "\n".join(
        f"| `{item['path']}` | {item['summary']} | {item['should_inform_storage_mapping']} | {item['conflict']} |"
        for item in discovery["legacy_framework_candidates"][:12]
    ) or "| none | none | false | none |"
    dir_rows = "\n".join(
        f"| `{item['path']}` | {item['intended_use']} | {item['evidence_status']} |"
        for item in mapping_doc["nas_folder_interpretation"]
    )
    mapping_rows = "\n".join(
        f"| `{item['path_id']}` | `{item['path']}` | {item['storage_tier']} | {item['purpose']} | {item['evidence_status']} |"
        for item in mapping_doc["mappings"]
    )
    drive_rows = "\n".join(
        f"| {letter}: | {info['exists']} | {info.get('total_human', '')} | {info.get('free_human', '')} |"
        for letter, info in inventory["drive_validation"].items()
    )
    package_rows = "\n".join(
        f"| {name} | {info['installed']} | `{info['install_command']}` |"
        for name, info in checklist["python_packages"].items()
    )
    return f"""# Data Foundation Readiness and Storage Mapping

## Hardware / NAS Facts

- Desktop: Julian-BASE, Windows 11 Pro 25H2 64-bit, Intel Core i7-9700K, 64GB RAM, GTX 1070 8GB.
- Local disks: C: KINGSTON SSD, D: SN570 SSD, E: Seagate HDD.
- NAS: NASTS464C2C / QNAP TS-464C2 / 192.168.0.103 / 32GB RAM / DataVol1 about 5.63TB with about 4.54TB free.
- Preferred NAS share: `Z:` -> `\\\\192.168.0.103\\financial_research`.
- `P:` is Public and is not the preferred FinancialResearch root.

## Legacy Storage Framework Discovery

Targeted search was run against FinancialResearch docs/runtime/config/project root, parse_lab docs/runtime/project root, and selected `Z:` directories only. No full NAS deep scan was performed.

| File | Summary | Use for mapping | Conflict |
|---|---|---:|---|
{legacy_rows}

Decision: `{discovery['decision']}`.

## Existing NAS Folder Interpretation

| Path | Intended use | Evidence |
|---|---|---|
{dir_rows}

`Z:/@Recently-Snapshot` and `Z:/@Recycle` are QNAP system directories and are not business data directories.

## Path Validation

| Drive | Exists | Total | Free |
|---|---:|---:|---:|
{drive_rows}

- `D:/workspace` exists.
- `D:/workspace/FinancialResearch` size: {inventory['project_sizes']['FinancialResearch']['size_human']}.
- `D:/workspace/parse_lab` size: {inventory['project_sizes']['parse_lab']['size_human']}.
- `D:/workspace/runtime` size: {inventory['project_sizes']['workspace_runtime']['size_human']}.
- Z readable: {inventory['nas_validation']['Z']['readable']}.
- Z writable small temp test: {inventory['nas_validation']['Z']['write_test']['success']}.

## Storage Path Mapping Draft

| Path ID | Path | Tier | Purpose | Evidence |
|---|---|---|---|---|
{mapping_rows}

This mapping aligns the new FR data foundation with the old NAS framework:

- raw source files map to `data_lake_master/raw`.
- parser-derived files map to `data_lake_master/parsed`.
- normalized consumption data maps to `data_lake_master/structured`.
- features and exports keep their existing framework locations.
- backups/logs/releases/contracts use the existing top-level NAS directories.

## Data Source Setup Checklist

| Package | Installed | Command |
|---|---:|---|
{package_rows}

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
"""


def walk_files_limited(root: Path, max_depth: int):
    root = root.resolve()
    stack = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    if entry.name in {".git", "__pycache__", "node_modules", "dist"}:
                        continue
                    try:
                        path = Path(entry.path)
                        if entry.is_file():
                            yield path
                        elif entry.is_dir() and depth < max_depth:
                            stack.append((path, depth + 1))
                    except OSError:
                        continue
        except OSError:
            continue


def scan_content_hits(path: Path) -> list[str]:
    if path.suffix.lower() not in {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".py", ".ps1", ".env", ".csv"}:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits = []
    lowered = text.lower()
    for keyword in KEYWORDS:
        if keyword.lower() in lowered:
            line = next((line.strip() for line in text.splitlines() if keyword.lower() in line.lower()), keyword)
            hits.append(line[:300])
        if len(hits) >= 5:
            break
    return hits


def summarize_legacy_file(path: Path, hits: list[str]) -> str:
    name = path.name.lower()
    if name.startswith("01_create_nas_financial_research_structure"):
        return "Old NAS financial_research directory creation script defining data_lake_master/incoming/backups/logs/release/contracts layers."
    if "data_storage_architecture" in name:
        return "Phase 1 data storage architecture doc."
    if "source_registry" in name or "data_connector" in name:
        return "Phase 1 connector/source registry doc."
    if "new_architecture" in name:
        return "Existing architecture doc mentioning optional NAS_ROOT."
    if hits:
        return hits[0]
    return "Keyword match."


def should_inform_storage_mapping(path: Path, hits: list[str]) -> bool:
    name = path.name.lower()
    if name.startswith("01_create_nas_financial_research_structure"):
        return True
    if path.suffix.lower() not in {".md", ".json", ".yaml", ".yml", ".ps1", ".env"}:
        return False
    meaningful_names = {
        "data_storage_architecture.md",
        "data_source_registry_schema.md",
        "data_connector_feasibility_audit.md",
        "financial_research_new_architecture.md",
        "local_project_inventory.md",
        ".env.example",
    }
    if name in meaningful_names:
        return True
    text = " ".join([name, *hits]).lower()
    return "data_lake_master" in text or "nas_root" in text or "storage architecture" in text


def legacy_candidate_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    path = item["path"].lower()
    if "01_create_nas_financial_research_structure" in path:
        return (0, path)
    if path.startswith("z:"):
        return (1, path)
    if "data_storage_architecture" in path:
        return (2, path)
    return (3, path)


def infer_conflict(path: Path, hits: list[str]) -> str:
    text = " ".join([path.name, *hits]).lower()
    if ("p:" in text or "\\public" in text or "public share" in text) and "financial_research" not in text:
        return "possible_public_share_reference_not_preferred"
    return "none_detected"


def is_generated_readiness_output(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return (
        resolved == DOC_PATH.resolve()
        or OUTPUT_ROOT.resolve() in resolved.parents
    )


def nas_folder_interpretation(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    old_file_found = bool(discovery["legacy_framework_candidates"])
    def item(path: str, use: str, status: str | None = None) -> dict[str, Any]:
        return {"path": path, "intended_use": use, "evidence_status": status or ("confirmed_from_old_file" if old_file_found else "inferred_from_folder_name")}
    return [
        item("Z:/data_lake_master", "FR data lake master root"),
        item("Z:/incoming", "external/manual download landing zone"),
        item("Z:/backups", "backup root"),
        item("Z:/logs_archive", "long-term log archive"),
        item("Z:/module_archives", "module archive root"),
        item("Z:/release_artifacts", "release/build artifact root"),
        item("Z:/shared_contracts_backup", "shared contract/schema/API backup root"),
        item("Z:/snapshots_note", "snapshot notes and restore runbook area"),
        item("Z:/@Recently-Snapshot", "QNAP system snapshot area, not business data", "confirmed_system_folder"),
        item("Z:/@Recycle", "QNAP recycle area, not business data; old script found here only as evidence", "confirmed_system_folder"),
    ]


def mapping(path_id: str, path: str, tier: str, purpose: str, evidence_status: str, exists: bool | None = None) -> dict[str, Any]:
    return {
        "path_id": path_id,
        "path": path,
        "storage_tier": tier,
        "purpose": purpose,
        "evidence_status": evidence_status,
        "exists": exists,
        "create_now": False,
    }


def drive_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}
    try:
        usage = shutil.disk_usage(path)
        return {
            "path": str(path),
            "exists": True,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "total_human": human_size(usage.total),
            "used_human": human_size(usage.used),
            "free_human": human_size(usage.free),
        }
    except OSError as exc:
        return {"path": str(path), "exists": True, "error": str(exc)}


def safe_dir_size(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", "dist"}]
        for file_name in files:
            try:
                total += (Path(root) / file_name).stat().st_size
            except OSError:
                continue
    return total


def is_readable(path: Path) -> bool:
    try:
        return path.exists() and any(path.iterdir())
    except OSError:
        return False


def z_write_test() -> dict[str, Any]:
    test_path = NAS_ROOT / f".fr_readiness_write_test_{os.getpid()}.tmp"
    try:
        test_path.write_text("FinancialResearch readiness write test\n", encoding="utf-8")
        checksum = hashlib.sha256(test_path.read_bytes()).hexdigest()
        test_path.unlink()
        return {"success": True, "test_path": str(test_path), "deleted": not test_path.exists(), "checksum": checksum}
    except OSError as exc:
        try:
            if test_path.exists():
                test_path.unlink()
        except OSError:
            pass
        return {"success": False, "test_path": str(test_path), "error": str(exc)}


def list_top_level(path: Path) -> list[str]:
    try:
        return sorted(item.name for item in path.iterdir())
    except OSError:
        return []


def human_size(size: int) -> str:
    value = float(size)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} TB"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
