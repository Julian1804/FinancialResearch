import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import SCHEMA_VERSION
from services.industry_profile_service import infer_company_industry_metric_profile
from services.metric_table_service import extract_table_metric_candidates, merge_metric_candidates
from services.period_service import allow_into_actuals, timeline_source_role
from services.research_utils import now_iso
from utils.file_utils import (
    build_metric_registry_path,
    get_extracted_json_files_in_company_folder,
    get_parsed_json_files_in_company_folder,
    load_json_file,
    save_json_file,
    sort_paths_by_year_and_name,
)

BASE_METRIC_ALIASES = {
    "revenue": ["revenue", "revenues", "营业收入", "收入", "收益", "營業收入", "收益總額"],
    "gross_profit": ["gross profit", "毛利", "毛利润", "毛利潤"],
    "gross_margin": ["gross margin", "gross profit margin", "毛利率", "整體毛利率"],
    "operating_profit": ["operating profit", "经营利润", "营业利润", "經營利潤", "營業利潤"],
    "operating_margin": ["operating margin", "营业利润率", "经营利润率", "營業利潤率"],
    "net_profit": [
        "net profit", "profit attributable", "profit attributable to owners",
        "归母净利润", "净利润", "本公司拥有人应占利润", "母公司拥有人应占利润",
        "本公司權益股東應佔溢利", "淨利潤"
    ],
    "adjusted_net_profit": ["adjusted net profit", "经调整净利润", "non-ifrs", "adjusted profit", "经调整利润"],
    "ebitda": ["ebitda", "息税折旧摊销前利润"],
    "operating_cash_flow": [
        "operating cash flow", "cash generated from operating activities",
        "net cash generated from operating activities",
        "经营活动现金流", "经营现金流", "經營活動所得現金流量淨額", "经营活动产生的现金流量净额"
    ],
    "free_cash_flow": ["free cash flow", "自由现金流"],
    "cash_and_equivalents": ["cash and cash equivalents", "现金及现金等价物", "現金及現金等價物"],
    "total_debt": ["total debt", "有息负债", "借款", "borrowings", "bank loans"],
    "net_cash": ["net cash", "净现金", "淨現金"],
    "capex": ["capital expenditure", "capex", "资本开支", "資本開支"],
    "accounts_receivable": ["accounts receivable", "trade receivables", "应收账款", "應收賬款"],
    "inventory": ["inventory", "inventories", "存货", "存貨"],
    "contract_liabilities": ["contract liabilities", "合同负债", "合約負債"],
    "r_and_d_expense": ["r&d", "研发费用", "research and development", "研發費用"],
    "selling_expense": ["selling expense", "销售费用", "銷售費用"],
    "admin_expense": ["administrative expense", "管理费用", "行政开支", "管理費用"],
    "order_backlog": ["backlog", "order backlog", "在手订单", "未完成订单", "new bookings"],
    "project_count": ["project count", "项目数", "项目数量", "ongoing projects"],
    "customer_count": ["customer count", "客户数", "active customers", "客户数量"],
    "utilization_rate": ["utilization", "utilization rate", "产能利用率", "稼动率", "利用率"],
    "production_volume": ["production volume", "产量", "產量"],
    "sales_volume": ["sales volume", "销量", "銷量", "出货量", "shipments"],
    "average_selling_price": ["asp", "average selling price", "平均售价", "平均销售单价"],
    "cash_cost": ["cash cost", "现金成本", "aisc", "all-in sustaining cost"],
    "arpu": ["arpu", "客单价", "每用户平均收入"],
    "channel_count": ["channel count", "渠道数量", "经销商数量", "终端覆盖"],
    "same_store_sales": ["same store sales", "same-store sales", "同店增长", "同店銷售"],
}

VALUE_REGEX = re.compile(
    r"(?P<label>[A-Za-z\u4e00-\u9fff\(\)（）\/\-\s]{2,80})[:：]?\s*"
    r"(?P<value>-?\d[\d,]*\.?\d*)\s*"
    r"(?P<unit>%|亿元|億元|百万元|百萬元|万元|萬元|million|billion|mn|bn)?",
    re.IGNORECASE
)
YOY_REGEX = re.compile(r"(同比|按年|year on year|yoy)[^\d\-+]*([\-+]?\d[\d,]*\.?\d*)\s*%", re.IGNORECASE)


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _build_aliases(company_folder: str | Path) -> Tuple[Dict[str, List[str]], dict]:
    profile = infer_company_industry_metric_profile(company_folder)
    aliases = {k: list(v) for k, v in BASE_METRIC_ALIASES.items()}
    for metric_name, extra_aliases in profile.get("aliases", {}).items():
        aliases.setdefault(metric_name, [])
        for alias in extra_aliases:
            if alias not in aliases[metric_name]:
                aliases[metric_name].append(alias)
    return aliases, profile


def _match_metric_name(label: str, aliases: Dict[str, List[str]]) -> Optional[str]:
    label_n = (label or "").strip().lower()
    if not label_n:
        return None
    for metric_name, items in aliases.items():
        for alias in items:
            if alias.lower() in label_n:
                return metric_name
    return None


def _extract_candidates_from_text(*, text: str, source_file: str, period_key: str, material_timestamp: str, aliases: Dict[str, List[str]], document_type: str, is_primary_financial_report_flag: bool) -> List[dict]:
    results = []
    text = text or ""
    source_role = timeline_source_role(document_type, is_primary_financial_report_flag)
    allow_actual = allow_into_actuals(document_type, is_primary_financial_report_flag)

    for match in VALUE_REGEX.finditer(text):
        label = (match.group("label") or "").strip()
        value = _safe_float(match.group("value"))
        unit = (match.group("unit") or "").strip()
        metric_name = _match_metric_name(label, aliases)

        if metric_name is None or value is None:
            continue

        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 120)
        snippet = text[start:end].replace("\n", " ").strip()

        yoy_match = YOY_REGEX.search(snippet)
        yoy_value = _safe_float(yoy_match.group(2)) if yoy_match else None

        score = 1.0
        if unit:
            score += 0.2
        if yoy_value is not None:
            score += 0.2
        if is_primary_financial_report_flag:
            score += 0.2

        results.append({
            "metric_name": metric_name,
            "raw_label": label,
            "value": value,
            "value_base": None,
            "prior_value": None,
            "prior_value_base": None,
            "unit": unit,
            "yoy_percent": yoy_value,
            "qoq_percent": None,
            "snippet": snippet,
            "source_file": source_file,
            "period_key": period_key,
            "material_timestamp": material_timestamp,
            "confidence": "medium",
            "extraction_method": "text_scan",
            "score": round(score, 3),
            "document_type": document_type,
            "is_primary_financial_report": is_primary_financial_report_flag,
            "source_role": source_role,
            "allow_into_actuals": allow_actual,
        })
    return results


def _deduplicate_candidates(candidates: List[dict]) -> List[dict]:
    seen = set()
    deduped = []
    for item in candidates:
        key = (
            item.get("metric_name", ""),
            item.get("period_key", ""),
            item.get("value"),
            item.get("unit", ""),
            item.get("source_file", ""),
            item.get("extraction_method", ""),
            item.get("document_type", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _build_output_paths(company_folder: str | Path) -> Tuple[Path, Path]:
    company_folder = Path(company_folder)
    analysis_dir = company_folder / "年报分析"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return analysis_dir / "standardized_metrics.json", analysis_dir / "metric_extraction_registry.json"


def extract_standardized_metrics(company_folder: str | Path) -> dict:
    company_folder = Path(company_folder)
    aliases, profile = _build_aliases(company_folder)

    parsed_files = sort_paths_by_year_and_name(get_parsed_json_files_in_company_folder(company_folder))
    extracted_files = sort_paths_by_year_and_name(get_extracted_json_files_in_company_folder(company_folder))

    extracted_map = {}
    for extracted_path in extracted_files:
        extracted_data = load_json_file(extracted_path)
        source_file = extracted_data.get("source_file", "")
        extracted_map[source_file] = extracted_data

    all_candidates = []
    source_summaries = []

    for parsed_path in parsed_files:
        parsed_data = load_json_file(parsed_path)
        source_file = parsed_data.get("source_file", Path(parsed_path).name)
        extracted_data = extracted_map.get(source_file, {})

        period_key = extracted_data.get("period_key", "")
        material_timestamp = extracted_data.get("material_timestamp", "")
        full_text = parsed_data.get("full_text", "")
        document_type = extracted_data.get("document_type", "other_disclosure")
        primary_flag = extracted_data.get("is_primary_financial_report", False)
        source_role = timeline_source_role(document_type, primary_flag)
        allow_actual = allow_into_actuals(document_type, primary_flag)

        table_candidates = extract_table_metric_candidates(
            text=full_text,
            source_file=source_file,
            period_key=period_key,
            material_timestamp=material_timestamp,
            document_type=document_type,
            is_primary_financial_report=primary_flag,
            source_role=source_role,
            allow_into_actuals=allow_actual,
        )

        text_candidates = _extract_candidates_from_text(
            text=full_text,
            source_file=source_file,
            period_key=period_key,
            material_timestamp=material_timestamp,
            aliases=aliases,
            document_type=document_type,
            is_primary_financial_report_flag=primary_flag,
        )

        candidates = merge_metric_candidates(table_candidates, text_candidates)
        candidates = _deduplicate_candidates(candidates)
        all_candidates.extend(candidates)

        source_summaries.append({
            "source_file": source_file,
            "period_key": period_key,
            "material_timestamp": material_timestamp,
            "document_type": document_type,
            "is_primary_financial_report": primary_flag,
            "source_role": source_role,
            "allow_into_actuals": allow_actual,
            "table_candidate_count": len(table_candidates),
            "text_candidate_count": len(text_candidates),
            "merged_candidate_count": len(candidates),
        })

    metric_groups: Dict[str, List[dict]] = {}
    for item in all_candidates:
        metric_groups.setdefault(item.get("metric_name", ""), []).append(item)

    for metric_name in metric_groups:
        metric_groups[metric_name].sort(
            key=lambda x: (
                1 if x.get("allow_into_actuals") else 0,
                x.get("period_key", ""),
                x.get("score", 0),
                x.get("material_timestamp", ""),
            ),
            reverse=True,
        )

    standardized_output = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "company_name": company_folder.name,
        "industry_metric_profile": profile,
        "metrics": metric_groups,
    }
    extraction_registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "company_name": company_folder.name,
        "industry_metric_profile": profile,
        "source_summaries": source_summaries,
        "total_candidate_count": len(all_candidates),
        "metric_names": sorted(list(metric_groups.keys())),
    }

    standardized_path, registry_path = _build_output_paths(company_folder)
    save_json_file(standardized_output, standardized_path)
    save_json_file(extraction_registry, registry_path)

    return {
        "status": "ok",
        "company_name": company_folder.name,
        "industry_metric_profile": profile,
        "standardized_metrics_path": str(standardized_path),
        "metric_extraction_registry_path": str(registry_path),
        "metric_names": sorted(list(metric_groups.keys())),
        "total_candidate_count": len(all_candidates),
        "metrics": metric_groups,
    }


def load_standardized_metrics(company_folder: str | Path) -> dict:
    standardized_path, _ = _build_output_paths(company_folder)
    if standardized_path.exists():
        return load_json_file(standardized_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "",
        "company_name": Path(company_folder).name,
        "industry_metric_profile": {"profile_name": "default", "profile_label": "通用", "recommended_metrics": [], "aliases": {}, "keyword_hit_score": 0},
        "metrics": {},
    }


def merge_selected_metrics_to_registry(company_folder: str | Path, selections: Dict[str, List[dict]]) -> dict:
    company_folder = Path(company_folder)
    registry_path = Path(build_metric_registry_path(company_folder))

    if registry_path.exists():
        metric_registry = load_json_file(registry_path)
    else:
        metric_registry = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "company_name": company_folder.name,
            "primary_timeline": [],
            "metric_values": {},
        }

    metric_registry.setdefault("metric_values", {})
    for metric_name, rows in selections.items():
        metric_registry["metric_values"][metric_name] = rows

    metric_registry["generated_at"] = now_iso()
    save_json_file(metric_registry, registry_path)
    return {"status": "ok", "metric_registry_path": str(registry_path), "updated_metrics": sorted(list(selections.keys()))}
