from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_data_foundation_readiness_audit import (  # noqa: E402
    DOC_PATH,
    NAS_ROOT,
    OUTPUT_ROOT,
    main as run_readiness_audit,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_readiness_outputs() -> None:
    exit_code = run_readiness_audit()
    assert exit_code == 0
    required = [
        OUTPUT_ROOT / "legacy_storage_framework_discovery.json",
        OUTPUT_ROOT / "local_storage_inventory.json",
        OUTPUT_ROOT / "storage_path_mapping_draft.json",
        OUTPUT_ROOT / "data_source_setup_checklist.json",
        OUTPUT_ROOT / "user_action_required.md",
        DOC_PATH,
    ]
    for path in required:
        assert path.exists(), f"missing output: {path}"


def test_legacy_framework_and_mapping() -> None:
    discovery = read_json(OUTPUT_ROOT / "legacy_storage_framework_discovery.json")
    assert discovery["legacy_framework_candidates"]
    assert discovery["decision"] == "use_existing_nas_framework_as_primary_mapping_source"
    assert any("01_CREATE_NAS_FINANCIAL_RESEARCH_STRUCTURE" in item["path"] for item in discovery["legacy_framework_candidates"])

    mapping = read_json(OUTPUT_ROOT / "storage_path_mapping_draft.json")
    paths = {item["path_id"]: item for item in mapping["mappings"]}
    assert paths["cold_data_root"]["path"] == "Z:/data_lake_master"
    assert paths["financial_report_pdf_root"]["path"] == "Z:/data_lake_master/raw/financial_reports"
    assert paths["normalized_data_root_cold"]["path"] == "Z:/data_lake_master/structured"
    assert paths["backup_root"]["path"] == "Z:/backups"
    assert "Z:/@Recycle" in mapping["do_not_use_as_business_dirs"]
    assert all(item["create_now"] is False for item in mapping["mappings"])


def test_path_validation_and_package_checklist() -> None:
    inventory = read_json(OUTPUT_ROOT / "local_storage_inventory.json")
    for drive in ["C", "D", "E", "P", "Z"]:
        assert inventory["drive_validation"][drive]["exists"] is True
    assert inventory["nas_validation"]["Z"]["readable"] is True
    assert inventory["nas_validation"]["Z"]["write_test"]["success"] is True
    assert inventory["nas_validation"]["Z"]["write_test"]["deleted"] is True
    assert not list(NAS_ROOT.glob(".fr_readiness_write_test_*.tmp"))

    checklist = read_json(OUTPUT_ROOT / "data_source_setup_checklist.json")
    for package in ["akshare", "baostock", "duckdb", "pyarrow", "pandas", "requests"]:
        assert package in checklist["python_packages"]
    assert checklist["data_sources"]["EIA"]["requires_api_key"] is True
    assert checklist["data_sources"]["Wind"]["requires_paid_or_license"] is True
    assert checklist["no_packages_installed_by_this_audit"] is True


def test_boundaries() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_readiness_outputs()
    test_legacy_framework_and_mapping()
    test_path_validation_and_package_checklist()
    test_boundaries()
    summary = read_json(OUTPUT_ROOT / "data_foundation_readiness_summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
