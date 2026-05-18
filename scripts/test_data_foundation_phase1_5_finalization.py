from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.finalize_data_foundation_phase1_5 import (  # noqa: E402
    FR_PYTHON,
    OUTPUT_ROOT,
    STORAGE_CONFIG_PATH,
    main as finalize_phase1_5,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_finalization_outputs() -> None:
    assert finalize_phase1_5() == 0
    for path in [
        OUTPUT_ROOT / "directory_creation_results.json",
        OUTPUT_ROOT / "storage_path_mapping_final.json",
        OUTPUT_ROOT / "python_package_install_results.json",
        STORAGE_CONFIG_PATH,
    ]:
        assert path.exists(), f"missing output: {path}"


def test_storage_paths_and_directories() -> None:
    config = read_json(STORAGE_CONFIG_PATH)
    paths = config["paths"]
    assert paths["cold_data_root"] == r"Z:\data_lake_master"
    assert paths["incoming_root"] == r"Z:\incoming"
    assert paths["financial_report_pdf_root"] == r"Z:\data_lake_master\raw\financial_reports"
    assert paths["raw_api_response_root"] == r"Z:\data_lake_master\raw\api_responses"
    assert paths["parser_raw_output_root"] == r"Z:\data_lake_master\parsed\financial_reports\parser_outputs"
    assert paths["trusted_consumption_root"] == r"Z:\data_lake_master\trusted_consumption"
    assert paths["backup_root"] == r"Z:\backups\FinancialResearch"
    assert paths["logs_archive_root"] == r"Z:\logs_archive\FinancialResearch"
    assert config["safety"]["no_existing_nas_dir_move_delete_rename"] is True
    for value in paths.values():
        if value.startswith("Z:\\") or value.startswith("E:\\"):
            assert Path(value).exists(), f"path should exist after finalization: {value}"

    directory_results = read_json(OUTPUT_ROOT / "directory_creation_results.json")
    assert all(row["moved_deleted_or_renamed_existing_data"] is False for row in directory_results["nas_directories"])
    assert all(row["exists_after"] is True for row in directory_results["nas_directories"])
    assert all(row["exists_after"] is True for row in directory_results["local_bulk_directories"])


def test_packages_installed_in_fr_env_only() -> None:
    package_results = read_json(OUTPUT_ROOT / "python_package_install_results.json")
    assert package_results["python_executable"] == str(FR_PYTHON)
    assert package_results["used_global_pip"] is False
    assert package_results["installed_to_parser_env"] is False
    assert all(row["import_success"] for row in package_results["packages"])
    versions = {row["package"]: row["pip_show_version"] for row in package_results["packages"]}
    assert versions["akshare"]
    assert versions["baostock"]
    assert versions["duckdb"]
    executable = subprocess.check_output(
        [str(FR_PYTHON), "-c", "import sys; print(sys.executable)"],
        text=True,
        encoding="utf-8",
    ).strip()
    assert executable.lower() == str(FR_PYTHON).lower()


def test_boundaries() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_finalization_outputs()
    test_storage_paths_and_directories()
    test_packages_installed_in_fr_env_only()
    test_boundaries()
    summary = read_json(OUTPUT_ROOT / "phase1_5_finalization_summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
