import json
import re
from pathlib import Path
from typing import List

from config.settings import DATA_DIR, SUBFOLDERS

UNICODE_ESCAPE_PATTERN = re.compile(r"#U([0-9A-Fa-f]{4,6})")


def display_company_name(company_name: str) -> str:
    if not company_name:
        return ""

    def _replace(match: re.Match) -> str:
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    return UNICODE_ESCAPE_PATTERN.sub(_replace, str(company_name))


def list_company_folders(data_dir: str | Path = DATA_DIR) -> List[str]:
    root = Path(data_dir)
    if not root.exists():
        return []
    return sorted([p.name for p in root.iterdir() if p.is_dir()])


def get_company_folder(company_name: str) -> Path:
    return Path(DATA_DIR) / company_name


def ensure_company_structure(company_name: str) -> Path:
    company_folder = get_company_folder(company_name)
    company_folder.mkdir(parents=True, exist_ok=True)
    for folder_name in SUBFOLDERS.values():
        (company_folder / folder_name).mkdir(parents=True, exist_ok=True)
    return company_folder


def get_pdf_files_in_company_folder(company_folder: str | Path) -> list:
    reports_folder = Path(company_folder) / SUBFOLDERS["raw"]
    if not reports_folder.exists():
        return []
    return sorted([str(p) for p in reports_folder.glob("*.pdf")])


def build_parsed_json_path(pdf_path: str | Path) -> str:
    pdf_path = Path(pdf_path)
    company_folder = pdf_path.parent.parent
    parsed_folder = company_folder / SUBFOLDERS["parsed"]
    parsed_folder.mkdir(parents=True, exist_ok=True)
    return str(parsed_folder / f"parsed_{pdf_path.stem}.json")


def build_page_images_folder(pdf_path: str | Path) -> str:
    pdf_path = Path(pdf_path)
    company_folder = pdf_path.parent.parent
    image_root = company_folder / SUBFOLDERS["page_images"] / pdf_path.stem
    image_root.mkdir(parents=True, exist_ok=True)
    return str(image_root)


def get_parsed_json_files_in_company_folder(company_folder: str | Path) -> list:
    parsed_folder = Path(company_folder) / SUBFOLDERS["parsed"]
    if not parsed_folder.exists():
        return []
    return sorted([str(p) for p in parsed_folder.glob("*.json")])


def build_extracted_json_path(parsed_json_path: str | Path) -> str:
    parsed_json_path = Path(parsed_json_path)
    company_folder = parsed_json_path.parent.parent
    extracted_folder = company_folder / SUBFOLDERS["extracted"]
    extracted_folder.mkdir(parents=True, exist_ok=True)
    name_without_ext = parsed_json_path.stem
    if name_without_ext.startswith("parsed_"):
        name_without_ext = name_without_ext[len("parsed_"):]
    return str(extracted_folder / f"extracted_{name_without_ext}.json")


def get_extracted_json_files_in_company_folder(company_folder: str | Path) -> list:
    extracted_folder = Path(company_folder) / SUBFOLDERS["extracted"]
    if not extracted_folder.exists():
        return []
    return sorted([str(p) for p in extracted_folder.glob("*.json")])


def build_report_json_path(extracted_json_path: str | Path) -> str:
    extracted_json_path = Path(extracted_json_path)
    company_folder = extracted_json_path.parent.parent
    report_folder = company_folder / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)
    name_without_ext = extracted_json_path.stem
    if name_without_ext.startswith("extracted_"):
        name_without_ext = name_without_ext[len("extracted_"):]
    return str(report_folder / f"report_{name_without_ext}.json")


def build_report_md_path(extracted_json_path: str | Path) -> str:
    extracted_json_path = Path(extracted_json_path)
    company_folder = extracted_json_path.parent.parent
    report_folder = company_folder / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)
    name_without_ext = extracted_json_path.stem
    if name_without_ext.startswith("extracted_"):
        name_without_ext = name_without_ext[len("extracted_"):]
    return str(report_folder / f"report_{name_without_ext}.md")


def get_report_json_files_in_company_folder(company_folder: str | Path) -> list:
    report_folder = Path(company_folder) / SUBFOLDERS["analysis"]
    if not report_folder.exists():
        return []
    return sorted([str(p) for p in report_folder.glob("report_*.json")])


def build_delta_json_path(extracted_json_path: str | Path) -> str:
    extracted_json_path = Path(extracted_json_path)
    company_folder = extracted_json_path.parent.parent
    report_folder = company_folder / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)
    name_without_ext = extracted_json_path.stem
    if name_without_ext.startswith("extracted_"):
        name_without_ext = name_without_ext[len("extracted_"):]
    return str(report_folder / f"delta_{name_without_ext}.json")


def build_history_memory_path(company_folder: str | Path) -> str:
    report_folder = Path(company_folder) / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)
    return str(report_folder / "history_memory.json")


def build_master_report_path(company_folder: str | Path) -> str:
    report_folder = Path(company_folder) / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)
    return str(report_folder / "master_report.json")


def build_forecast_check_json_path(base_report_path: str | Path, actual_extracted_path: str | Path) -> str:
    base_report_path = Path(base_report_path)
    actual_extracted_path = Path(actual_extracted_path)
    company_folder = base_report_path.parent.parent
    report_folder = company_folder / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)

    base_name = base_report_path.stem
    actual_name = actual_extracted_path.stem
    if base_name.startswith("report_"):
        base_name = base_name[len("report_"):]
    if actual_name.startswith("extracted_"):
        actual_name = actual_name[len("extracted_"):]
    return str(report_folder / f"forecast_check_{base_name}_to_{actual_name}.json")


def build_index_json_path(company_folder: str | Path) -> str:
    return str(Path(company_folder) / "index.json")


def build_timeline_json_path(company_folder: str | Path) -> str:
    return str(Path(company_folder) / "timeline_index.json")


def build_qa_index_dir(company_folder: str | Path) -> str:
    folder = Path(company_folder) / SUBFOLDERS["qa_index"]
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def build_qa_chunks_path(company_folder: str | Path) -> str:
    return str(Path(build_qa_index_dir(company_folder)) / "research_chunks.json")


def _sanitize_metric_name(metric_name: str) -> str:
    metric_name = str(metric_name or "").strip().lower()
    metric_name = re.sub(r"[^a-z0-9_]+", "_", metric_name)
    return metric_name.strip("_") or "metric"


def build_metric_registry_path(company_folder: str | Path) -> str:
    report_folder = Path(company_folder) / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)
    return str(report_folder / "metric_series_registry.json")


def build_forecast_registry_path(company_folder: str | Path) -> str:
    report_folder = Path(company_folder) / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)
    return str(report_folder / "forecast_registry.json")


def build_forecast_snapshot_json_path(
    company_folder: str | Path,
    metric_name: str,
    forecast_as_of_period: str,
    forecast_target_period: str
) -> str:
    report_folder = Path(company_folder) / SUBFOLDERS["analysis"]
    report_folder.mkdir(parents=True, exist_ok=True)
    safe_metric = _sanitize_metric_name(metric_name)
    safe_as_of = str(forecast_as_of_period or "UNKNOWN")
    safe_target = str(forecast_target_period or "UNKNOWN")
    return str(report_folder / f"forecast_snapshot_{safe_metric}_{safe_as_of}_to_{safe_target}.json")


def get_forecast_snapshot_files_in_company_folder(company_folder: str | Path) -> list:
    report_folder = Path(company_folder) / SUBFOLDERS["analysis"]
    if not report_folder.exists():
        return []
    return sorted([str(p) for p in report_folder.glob("forecast_snapshot_*.json")])


def load_json_file(json_path: str | Path) -> dict:
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(data: dict, json_path: str | Path) -> None:
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_text_file(text: str, file_path: str | Path) -> None:
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)


def extract_sort_key_from_filename(path: str | Path):
    filename = Path(path).name
    years = re.findall(r"(19\d{2}|20\d{2})", filename)
    if years:
        return (int(years[0]), filename)
    return (9999, filename)


def sort_paths_by_year_and_name(paths: list) -> list:
    return sorted(paths, key=extract_sort_key_from_filename)