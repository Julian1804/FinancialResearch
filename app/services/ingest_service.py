from pathlib import Path

from services.extractor_service import build_extracted_output
from services.metric_extraction_service import extract_standardized_metrics
from services.parser_service import build_parsed_output, save_parsed_json
from services.repository_service import refresh_company_repository
from utils.file_utils import build_extracted_json_path, build_parsed_json_path, load_json_file, save_json_file


def run_ingest_pipeline(company_name: str, pdf_path: str | Path, run_extract: bool = True, run_metrics: bool = True) -> dict:
    pdf_path = Path(pdf_path)
    company_folder = pdf_path.parent.parent

    parsed_data = build_parsed_output(company_name=company_name, file_path=str(pdf_path))
    parsed_path = build_parsed_json_path(pdf_path)
    save_parsed_json(parsed_data, parsed_path)

    extracted_data = None
    extracted_path = None
    metrics_result = None

    if run_extract:
        extracted_data = build_extracted_output(parsed_data)
        extracted_path = build_extracted_json_path(parsed_path)
        save_json_file(extracted_data, extracted_path)

    if run_metrics:
        metrics_result = extract_standardized_metrics(company_folder)

    refresh_company_repository(company_folder)
    return {
        "parsed_data": parsed_data,
        "parsed_path": str(parsed_path),
        "extracted_data": extracted_data,
        "extracted_path": str(extracted_path) if extracted_path else "",
        "metrics_result": metrics_result or {},
    }
