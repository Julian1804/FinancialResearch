import re
from typing import Dict, Optional

REPORT_TYPE_ORDER = {
    "Q1": 1,
    "H1": 2,
    "Q3": 3,
    "FY": 4,
}

PRIMARY_REPORT_KEYWORDS = [
    "annual report", "interim report", "quarterly report", "first quarterly report", "third quarterly report",
    "half year report", "half-year report", "semi annual report", "semi-annual report", "mid year report", "mid-year report",
    "年度报告", "年度報告", "中期报告", "中期報告", "中期年报", "中期年報", "半年度报告", "半年度報告",
    "季度报告", "季度報告", "第一季度报告", "第一季度報告", "第三季度报告", "第三季度報告",
    "年报", "年報", "中报", "中報", "半年报", "半年報", "一季报", "一季報", "三季报", "三季報",
]

AUX_PATTERNS = {
    "earnings_preannouncement": [
        "业绩预告", "盈利预警", "盈利警告", "盈喜", "盈警",
        "profit warning", "positive profit alert", "earnings preannouncement", "preliminary earnings estimate", "guidance update",
    ],
    "earnings_release": [
        "业绩公告", "业绩發布", "业绩发布", "全年业绩公告", "中期业绩公告", "年度业绩公告",
        "results announcement", "results release", "earnings release", "news release",
        "annual results announcement", "interim results announcement", "quarterly results announcement",
        "全年业绩新闻稿", "全年業績新聞稿", "中期业绩新闻稿", "中期業績新聞稿",
    ],
    "earnings_presentation": [
        "业绩简报", "业绩说明", "业绩演示", "路演材料", "发布会材料",
        "presentation", "results presentation", "earnings presentation", "investor presentation",
    ],
    "investor_communication": [
        "投资者关系", "投资者交流", "投资者会议", "电话会议", "电话会", "電話會",
        "conference call", "investor communication", "investor call",
    ],
    "operational_update": [
        "经营数据", "运营数据", "operational update", "monthly operational",
    ],
}

FILENAME_AUX_HINTS = [kw for items in AUX_PATTERNS.values() for kw in items]


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    return str(text).strip()


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _normalize_for_match(text: str) -> str:
    text = normalize_text(text).lower()
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = text.replace("—", " ")
    text = text.replace("–", " ")
    return text


def detect_fiscal_year(source_file: str, text: str) -> Optional[int]:
    source_file = normalize_text(source_file)
    text = normalize_text(text)
    combined = f"{source_file}\n{text[:30000]}"

    years = re.findall(r"(19\d{2}|20\d{2})", combined)
    if not years:
        return None

    file_years = re.findall(r"(19\d{2}|20\d{2})", source_file)
    if file_years:
        return int(file_years[0])

    return int(years[0])


def detect_report_type(source_file: str, text: str) -> str:
    source_file_n = _normalize_for_match(source_file)
    text_n = _normalize_for_match(text[:25000])
    combined = f"{source_file_n}\n{text_n}"

    h1_keywords = [
        "interim report", "interim results", "half year report", "half year results",
        "half-year report", "half-year results", "semi annual report", "semi annual results",
        "semi-annual report", "semi-annual results", "mid year report", "mid year results",
        "mid-year report", "mid-year results", "中期报告", "中期報告", "中报", "中報",
        "半年报", "半年報", "半年度报告", "半年度報告", "中期年报", "中期年報",
        "中期业绩", "中期業績", "半年度业绩", "半年度業績", "上半年业绩", "上半年業績",
        "中期业绩新闻稿", "中期業績新聞稿", "中期业绩公告", "中期業績公告",
    ]
    if _contains_any(combined, h1_keywords):
        return "H1"

    q3_keywords = [
        "third quarterly report", "third quarter report", "third quarter results",
        "q3 results", "9m results", "nine months results", "nine-month results",
        "第三季度报告", "第三季度報告", "三季报", "三季報", "第三季度业绩", "第三季度業績",
        "前三季度业绩", "前三季度業績",
    ]
    if _contains_any(combined, q3_keywords):
        return "Q3"

    q1_keywords = [
        "first quarterly report", "first quarter report", "first quarter results",
        "q1 results", "quarter 1 results", "第一季度报告", "第一季度報告", "一季报", "一季報",
        "第一季度业绩", "第一季度業績", "一季度业绩", "一季度業績",
    ]
    if _contains_any(combined, q1_keywords):
        return "Q1"

    fy_keywords = [
        "annual report", "annual results", "final results", "full year results", "full-year results",
        "fy results", "year end results", "年度报告", "年度報告", "年报", "年報",
        "全年业绩", "全年業績", "年度业绩", "年度業績", "全年业绩新闻稿", "全年業績新聞稿",
        "全年业绩公告", "全年業績公告", "年度业绩公告", "年度業績公告",
    ]
    if _contains_any(combined, fy_keywords):
        return "FY"

    if "quarterly report" in combined or "季度报告" in combined or "季度報告" in combined:
        return "UNKNOWN"

    return "UNKNOWN"


def _detect_aux_document_type(source_file_n: str, text_n: str) -> str:
    filename_only = source_file_n
    first_text = text_n[:12000]
    for doc_type, keywords in AUX_PATTERNS.items():
        if _contains_any(filename_only, keywords):
            return doc_type
    for doc_type, keywords in AUX_PATTERNS.items():
        if _contains_any(first_text, keywords):
            return doc_type
    return ""


def _looks_like_primary_filename(source_file_n: str) -> bool:
    if _contains_any(source_file_n, FILENAME_AUX_HINTS):
        return False
    return _contains_any(source_file_n, PRIMARY_REPORT_KEYWORDS)


def detect_document_type(source_file: str, text: str, report_type: str) -> str:
    source_file_n = _normalize_for_match(source_file)
    text_n = _normalize_for_match(text[:30000])

    aux_type = _detect_aux_document_type(source_file_n, text_n)
    if aux_type:
        return aux_type

    if _looks_like_primary_filename(source_file_n):
        return "financial_report"

    if _contains_any(text_n, PRIMARY_REPORT_KEYWORDS):
        return "financial_report"

    if report_type in {"Q1", "H1", "Q3", "FY"}:
        return "other_disclosure"

    return "other_disclosure"


def build_period_key(fiscal_year: Optional[int], report_type: str) -> str:
    if not fiscal_year or report_type not in {"Q1", "H1", "Q3", "FY"}:
        return ""
    return f"{fiscal_year}{report_type}"


def is_annual_final(report_type: str) -> bool:
    return report_type == "FY"


def is_primary_financial_report(report_type: str, document_type: str) -> bool:
    return document_type == "financial_report" and report_type in {"Q1", "H1", "Q3", "FY"}


def can_adjust_forecast(report_type: str, document_type: str) -> bool:
    if document_type == "financial_report" and report_type in {"Q1", "H1", "Q3", "FY"}:
        return True
    if document_type in {"earnings_preannouncement", "earnings_release", "earnings_presentation", "investor_communication", "operational_update"}:
        return True
    return False


def extract_report_date(text: str, source_file: str = "") -> str:
    combined = f"{normalize_text(source_file)}\n{normalize_text(text)[:30000]}"
    patterns = [
        r"(20\d{2}-\d{1,2}-\d{1,2})", r"(20\d{2}/\d{1,2}/\d{1,2})", r"(20\d{2}\.\d{1,2}\.\d{1,2})",
        r"(20\d{2}年\d{1,2}月\d{1,2}日)", r"(20\d{2}年\d{1,2}月)", r"(20\d{2}/\d{1,2})", r"(20\d{2}-\d{1,2})",
        r"(20\d{2}\.\d{1,2})", r"(20\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, combined)
        if match:
            return match.group(1)
    return ""


def normalize_material_timestamp(date_text: str) -> Dict[str, str]:
    date_text = normalize_text(date_text)
    if not date_text:
        return {"material_timestamp": "", "material_timestamp_precision": "unknown"}
    date_text = date_text.replace("/", "-").replace(".", "-")
    for pattern, precision in [
        (r"(20\d{2})-(\d{1,2})-(\d{1,2})", "day"),
        (r"(20\d{2})年(\d{1,2})月(\d{1,2})日", "day"),
        (r"(20\d{2})-(\d{1,2})", "month"),
        (r"(20\d{2})年(\d{1,2})月", "month"),
        (r"(20\d{2})", "year"),
    ]:
        m = re.fullmatch(pattern, date_text)
        if m:
            parts = [int(x) for x in m.groups()]
            if precision == "day":
                y, mm, dd = parts
                return {"material_timestamp": f"{y:04d}-{mm:02d}-{dd:02d}", "material_timestamp_precision": precision}
            if precision == "month":
                y, mm = parts
                return {"material_timestamp": f"{y:04d}-{mm:02d}", "material_timestamp_precision": precision}
            y = parts[0]
            return {"material_timestamp": f"{y:04d}", "material_timestamp_precision": precision}
    return {"material_timestamp": date_text, "material_timestamp_precision": "raw"}


def related_primary_period_key(fiscal_year: Optional[int], report_type: str, document_type: str, primary_flag: bool, period_key: str) -> str:
    if primary_flag:
        return period_key
    if fiscal_year and report_type in {"Q1", "H1", "Q3", "FY"}:
        return f"{fiscal_year}{report_type}"
    return ""


def infer_timeline_bucket(primary_flag: bool, document_type: str) -> str:
    if primary_flag:
        return "primary"
    if document_type in {"earnings_preannouncement", "earnings_release", "earnings_presentation", "investor_communication", "operational_update"}:
        return "auxiliary"
    return "other"


def infer_forecast_periods(fiscal_year: Optional[int], report_type: str, document_type: str, period_key: str, is_primary: bool) -> Dict[str, str]:
    forecast_as_of_period = ""
    forecast_target_period = ""
    if is_primary and period_key:
        forecast_as_of_period = period_key
        if fiscal_year and report_type in {"Q1", "H1", "Q3"}:
            forecast_target_period = f"{fiscal_year}FY"
        elif fiscal_year and report_type == "FY":
            forecast_target_period = f"{fiscal_year + 1}FY"
        return {"forecast_as_of_period": forecast_as_of_period, "forecast_target_period": forecast_target_period}
    if fiscal_year and document_type != "financial_report":
        forecast_as_of_period = f"{fiscal_year}AUX"
        if report_type in {"Q1", "H1", "Q3"}:
            forecast_target_period = f"{fiscal_year}FY"
        elif report_type == "FY":
            forecast_target_period = f"{fiscal_year + 1}FY"
        else:
            forecast_target_period = f"{fiscal_year}FY"
    return {"forecast_as_of_period": forecast_as_of_period, "forecast_target_period": forecast_target_period}


def build_period_metadata(source_file: str, text: str) -> Dict[str, object]:
    fiscal_year = detect_fiscal_year(source_file, text)
    report_type = detect_report_type(source_file, text)
    period_key = build_period_key(fiscal_year, report_type)
    document_type = detect_document_type(source_file, text, report_type)
    primary_flag = is_primary_financial_report(report_type, document_type)
    rel_primary_key = related_primary_period_key(fiscal_year, report_type, document_type, primary_flag, period_key)
    timeline_bucket = infer_timeline_bucket(primary_flag, document_type)
    report_date = extract_report_date(text, source_file)
    timestamp_info = normalize_material_timestamp(report_date)
    forecast_periods = infer_forecast_periods(fiscal_year, report_type, document_type, period_key, primary_flag)
    return {
        "fiscal_year": fiscal_year if fiscal_year else None,
        "report_type": report_type,
        "period_key": period_key,
        "related_primary_period_key": rel_primary_key,
        "document_type": document_type,
        "timeline_bucket": timeline_bucket,
        "report_date": report_date,
        "material_timestamp": timestamp_info["material_timestamp"],
        "material_timestamp_precision": timestamp_info["material_timestamp_precision"],
        "is_annual_final": is_annual_final(report_type),
        "is_primary_financial_report": primary_flag,
        "can_adjust_forecast": can_adjust_forecast(report_type, document_type),
        "forecast_as_of_period": forecast_periods["forecast_as_of_period"],
        "forecast_target_period": forecast_periods["forecast_target_period"],
    }


def period_sort_tuple(period_key: str):
    if not period_key:
        return (9999, 99, "")
    match = re.match(r"^(19\d{2}|20\d{2})(Q1|H1|Q3|FY)$", period_key)
    if match:
        year = int(match.group(1))
        rtype = match.group(2)
        return (year, REPORT_TYPE_ORDER[rtype], period_key)
    aux_match = re.match(r"^(19\d{2}|20\d{2})AUX$", period_key)
    if aux_match:
        year = int(aux_match.group(1))
        return (year, 5, period_key)
    return (9999, 99, period_key)


def timeline_source_role(document_type: str, is_primary_financial_report_flag: bool) -> str:
    if is_primary_financial_report_flag:
        return "primary_timeline"
    if document_type in {"earnings_preannouncement", "earnings_release", "earnings_presentation", "investor_communication", "operational_update"}:
        return "auxiliary_signal"
    return "other"


def allow_into_actuals(document_type: str, is_primary_financial_report_flag: bool) -> bool:
    return bool(is_primary_financial_report_flag and document_type == "financial_report")
