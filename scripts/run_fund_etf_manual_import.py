from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_fund_etf_capital_flow_foundation import RUNTIME_ROOT, TEMPLATE_DEFINITIONS, run as generate_foundation  # noqa: E402
from scripts.run_morningstar_safe_access_audit import write_json  # noqa: E402


IMPORT_ROOT = RUNTIME_ROOT / "manual_import_runs"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def blank(value: str | None) -> bool:
    return value is None or str(value).strip() == ""


def validate_date(value: str | None) -> bool:
    if blank(value):
        return False
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except ValueError:
        return False


def validate_fund_code(value: str | None) -> bool:
    if blank(value):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{1,32}", str(value).strip()))


def infer_code_field(template_name: str) -> str:
    if template_name == "exchange_etf_list_template.csv":
        return "etf_code"
    if template_name == "fund_holdings_template.csv":
        return "fund_id"
    return "fund_code"


def validate_import(input_path: Path, template_name: str) -> dict[str, Any]:
    if template_name not in TEMPLATE_DEFINITIONS:
        raise ValueError(f"Unknown template: {template_name}")
    spec = TEMPLATE_DEFINITIONS[template_name]
    rows = read_csv(input_path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    code_field = infer_code_field(template_name)

    for idx, row in enumerate(rows, start=2):
        for field in spec["required"]:
            if blank(row.get(field)):
                errors.append({"row": idx, "field": field, "error": "required_field_missing"})
        if code_field in row and not blank(row.get(code_field)) and not validate_fund_code(row.get(code_field)):
            errors.append({"row": idx, "field": code_field, "error": "invalid_code_format"})
        date_field = "publish_date" if "publish_date" in row else "disclosure_date"
        if date_field in row and not blank(row.get(date_field)) and not validate_date(row.get(date_field)):
            errors.append({"row": idx, "field": date_field, "error": "invalid_date_format_expected_yyyy_mm_dd"})
        key = (str(row.get("source_id", "")).strip(), str(row.get(code_field, "")).strip())
        if key[0] and key[1]:
            if key in seen_keys:
                errors.append({"row": idx, "field": code_field, "error": "duplicate_source_code"})
            seen_keys.add(key)
        if row.get("official_or_third_party") not in {"official", "issuer_official", "exchange_official", "regulator_official", "third_party", ""}:
            warnings.append({"row": idx, "field": "official_or_third_party", "warning": "unrecognized_source_classification"})

    quality_status = "quality_passed" if not errors else "quality_failed"
    if not errors and warnings:
        quality_status = "quality_warning"
    result = {
        "generated_at": utc_now(),
        "input_path": str(input_path),
        "template_name": template_name,
        "row_count": len(rows),
        "quality_status": quality_status,
        "errors": errors,
        "warnings": warnings,
        "candidate_only": True,
        "manual_import_not_auto_trusted": True,
    }
    IMPORT_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(IMPORT_ROOT / "latest_manual_import_validation_result.json", result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate FR fund/ETF manual import files.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-templates")
    validate = sub.add_parser("validate")
    validate.add_argument("--input", required=True)
    validate.add_argument("--template", required=True)
    args = parser.parse_args()

    if args.command == "generate-templates":
        result = generate_foundation()
        print(json.dumps({"templates": result["import_templates"], "root": str(RUNTIME_ROOT)}, ensure_ascii=False, indent=2))
        return
    result = validate_import(Path(args.input), args.template)
    print(json.dumps({"quality_status": result["quality_status"], "row_count": result["row_count"], "errors": len(result["errors"])}, indent=2))


if __name__ == "__main__":
    main()
