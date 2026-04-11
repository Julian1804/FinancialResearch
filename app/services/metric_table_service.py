import re
from typing import Any, Dict, List, Optional, Tuple


STANDARD_UNIT_TO_BASE = {
    "元": 1.0,
    "万元": 10000.0,
    "百万元": 1000000.0,
    "亿元": 100000000.0,
    "thousand": 1000.0,
    "million": 1000000.0,
    "billion": 1000000000.0,
    "%": 1.0,
}

UNIT_ALIASES = {
    "元": "元",
    "万元": "万元",
    "萬元": "万元",
    "百万元": "百万元",
    "百萬元": "百万元",
    "亿元": "亿元",
    "億元": "亿元",
    "thousand": "thousand",
    "thousands": "thousand",
    "million": "million",
    "millions": "million",
    "mn": "million",
    "billion": "billion",
    "billions": "billion",
    "bn": "billion",
    "%": "%",
}

METRIC_PATTERNS = {
    "revenue": [
        "营业收入", "營業收入", "收入", "收益", "revenue", "revenues"
    ],
    "net_profit": [
        "归母净利润", "淨利潤", "净利润", "本公司拥有人应占利润",
        "本公司權益股東應佔溢利", "profit attributable", "net profit"
    ],
    "gross_margin": [
        "毛利率", "gross margin", "gross profit margin"
    ],
    "operating_cash_flow": [
        "经营活动产生的现金流量净额",
        "經營活動所得現金流量淨額",
        "经营现金流",
        "operating cash flow",
        "cash generated from operating activities",
    ],
}

TABLE_LINE_SEPARATORS = ["\t", "│", "|", "｜"]


def normalize_unit(unit: str) -> str:
    unit = (unit or "").strip()
    if not unit:
        return ""
    lower = unit.lower()
    return UNIT_ALIASES.get(unit, UNIT_ALIASES.get(lower, unit))


def unit_to_multiplier(unit: str) -> Optional[float]:
    unit_n = normalize_unit(unit)
    return STANDARD_UNIT_TO_BASE.get(unit_n)


def normalize_numeric_text(text: str) -> str:
    text = (text or "").strip()
    text = text.replace(",", "")
    text = text.replace("，", "")
    text = text.replace("（", "(").replace("）", ")")
    return text


def safe_float(text: Any) -> Optional[float]:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)

    s = normalize_numeric_text(str(text))
    if not s:
        return None

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()

    try:
        value = float(s)
        return -value if negative else value
    except Exception:
        return None


def convert_value_to_base(value: Optional[float], unit: str) -> Tuple[Optional[float], str]:
    if value is None:
        return None, normalize_unit(unit)

    unit_n = normalize_unit(unit)
    mul = unit_to_multiplier(unit_n)
    if mul is None:
        return value, unit_n
    return value * mul, unit_n


def detect_metric_name(label: str) -> Optional[str]:
    label_n = (label or "").strip().lower()
    if not label_n:
        return None

    for metric_name, aliases in METRIC_PATTERNS.items():
        for alias in aliases:
            if alias.lower() in label_n:
                return metric_name
    return None


def looks_like_table_line(line: str) -> bool:
    line = (line or "").strip()
    if not line:
        return False

    if any(sep in line for sep in TABLE_LINE_SEPARATORS):
        return True

    num_count = len(re.findall(r"-?\d[\d,]*\.?\d*%?", line))
    if num_count >= 3 and len(line) <= 220:
        return True

    return False


def split_table_line(line: str) -> List[str]:
    raw = line.strip()
    for sep in TABLE_LINE_SEPARATORS:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep)]
            return [p for p in parts if p]

    parts = re.split(r"\s{2,}", raw)
    return [p.strip() for p in parts if p.strip()]


def detect_unit_from_line(line: str) -> str:
    line_n = line.lower()
    for alias in list(UNIT_ALIASES.keys()):
        if alias.lower() in line_n:
            return normalize_unit(alias)
    return ""


def extract_percent_from_text(text: str) -> Optional[float]:
    m = re.search(r"([\-+]?\d[\d,]*\.?\d*)\s*%", text or "")
    if not m:
        return None
    return safe_float(m.group(1))


def classify_value_columns(cells: List[str]) -> Dict[str, Optional[str]]:
    """
    尝试把一行表格拆成：
    - label
    - current_value
    - prior_value
    - yoy_percent
    - qoq_percent
    """
    result = {
        "label": None,
        "current_value": None,
        "prior_value": None,
        "yoy_percent": None,
        "qoq_percent": None,
    }
    if not cells:
        return result

    result["label"] = cells[0]

    numeric_like = []
    for item in cells[1:]:
        numeric_like.append(item)

    percent_items = []
    value_items = []
    for item in numeric_like:
        if "%" in item:
            percent_items.append(item)
        else:
            value_items.append(item)

    if value_items:
        result["current_value"] = value_items[0]
    if len(value_items) >= 2:
        result["prior_value"] = value_items[1]

    if percent_items:
        result["yoy_percent"] = percent_items[0]
    if len(percent_items) >= 2:
        result["qoq_percent"] = percent_items[1]

    return result


def extract_table_metric_candidates(
    text: str,
    source_file: str,
    period_key: str,
    material_timestamp: str,
    document_type: str = "",
    is_primary_financial_report: bool = False,
    source_role: str = "",
    allow_into_actuals: bool = False,
) -> List[dict]:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    results = []

    # 先保留最近出现的“单位说明”
    recent_unit = ""

    for idx, line in enumerate(lines):
        if not line:
            continue

        line_unit = detect_unit_from_line(line)
        if line_unit:
            recent_unit = line_unit

        if not looks_like_table_line(line):
            continue

        cells = split_table_line(line)
        if len(cells) < 2:
            continue

        classified = classify_value_columns(cells)
        label = classified["label"] or ""
        metric_name = detect_metric_name(label)
        if metric_name is None:
            continue

        current_value_raw = classified["current_value"]
        prior_value_raw = classified["prior_value"]
        yoy_percent_raw = classified["yoy_percent"]
        qoq_percent_raw = classified["qoq_percent"]

        current_value = safe_float(current_value_raw)
        prior_value = safe_float(prior_value_raw)
        yoy_percent = extract_percent_from_text(yoy_percent_raw or "")
        qoq_percent = extract_percent_from_text(qoq_percent_raw or "")

        if current_value is None and yoy_percent is None:
            continue

        unit = detect_unit_from_line(line) or recent_unit
        base_value, normalized_unit = convert_value_to_base(current_value, unit)
        prior_base_value, _ = convert_value_to_base(prior_value, unit)

        snippet_start = max(0, idx - 1)
        snippet_end = min(len(lines), idx + 2)
        snippet = " | ".join(lines[snippet_start:snippet_end])

        score = 2.0
        if base_value is not None:
            score += 1.0
        if prior_base_value is not None:
            score += 0.4
        if yoy_percent is not None:
            score += 0.4
        if qoq_percent is not None:
            score += 0.3
        if normalized_unit:
            score += 0.2

        results.append({
            "metric_name": metric_name,
            "raw_label": label,
            "value": current_value,
            "value_base": base_value,
            "prior_value": prior_value,
            "prior_value_base": prior_base_value,
            "unit": normalized_unit,
            "yoy_percent": yoy_percent,
            "qoq_percent": qoq_percent,
            "source_file": source_file,
            "period_key": period_key,
            "material_timestamp": material_timestamp,
            "snippet": snippet,
            "extraction_method": "table_line",
            "confidence": "high" if score >= 3.0 else "medium",
            "score": round(score, 3),
            "document_type": document_type,
            "is_primary_financial_report": is_primary_financial_report,
            "source_role": source_role,
            "allow_into_actuals": allow_into_actuals,
        })

    return results


def merge_metric_candidates(table_candidates: List[dict], text_candidates: List[dict]) -> List[dict]:
    all_items = []
    seen = set()

    for item in table_candidates + text_candidates:
        key = (
            item.get("metric_name", ""),
            item.get("period_key", ""),
            item.get("value"),
            item.get("unit", ""),
            item.get("source_file", ""),
            item.get("extraction_method", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        all_items.append(item)

    all_items.sort(
        key=lambda x: (
            x.get("metric_name", ""),
            x.get("period_key", ""),
            x.get("score", 0),
            x.get("material_timestamp", ""),
        ),
        reverse=True,
    )
    return all_items