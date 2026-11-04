"""China-region Equity source representations and venue-specific promotion contracts."""

from __future__ import annotations

import io
import json
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping

from openpyxl import load_workbook

from backend.app.core.artifact_io import canonical_json, stable_key
from backend.app.core.source_transport import sha256_bytes


DAILY_METRIC_CONTRACT: dict[str, tuple[str, str, str, str, float, str, str]] = {
    "equity.open": ("open", "daily_ohlc", "CNY/share", "CNY", 1.0, "currency_per_share", "CNY"),
    "equity.high": ("high", "daily_ohlc", "CNY/share", "CNY", 1.0, "currency_per_share", "CNY"),
    "equity.low": ("low", "daily_ohlc", "CNY/share", "CNY", 1.0, "currency_per_share", "CNY"),
    "equity.close": ("close", "daily_ohlc", "CNY/share", "CNY", 1.0, "currency_per_share", "CNY"),
    "market.volume": ("volume_lots", "market_volume", "lots", "not_applicable", 100.0, "shares", "not_applicable"),
    "market.trade_amount": ("trade_amount_reported", "market_trade_amount", "ten_thousand_CNY", "CNY", 10000.0, "currency", "CNY"),
    "market.turnover_rate": ("turnover_percent", "market_turnover_rate", "percent", "not_applicable", 0.01, "decimal_ratio", "not_applicable"),
}

# Sina's integer/decimal JavaScript codec can expose an otherwise valid HKEX
# unadjusted price exactly 1e-5 away from the exchange price grid (for example
# 484.79999 for 484.8). The exact tolerance avoids rounding arbitrary
# higher-precision values whose economic meaning has not been proved.
SINA_HK_PRICE_CODEC_TAIL = Decimal("0.00001")


@dataclass(frozen=True)
class HKEXSpreadBand:
    lower: Decimal
    upper: Decimal
    spread: Decimal
    lower_inclusive: bool = False

    def contains(self, value: Decimal) -> bool:
        lower_match = value >= self.lower if self.lower_inclusive else value > self.lower
        return lower_match and value <= self.upper


@dataclass(frozen=True)
class HKEXSpreadSchedule:
    schedule_id: str
    effective_from: date
    authority_url: str
    bands: tuple[HKEXSpreadBand, ...]


def _spread_bands(rows: tuple[tuple[str, str, str], ...]) -> tuple[HKEXSpreadBand, ...]:
    return tuple(
        HKEXSpreadBand(
            lower=Decimal(lower), upper=Decimal(upper), spread=Decimal(spread),
            lower_inclusive=index == 0,
        )
        for index, (lower, upper, spread) in enumerate(rows)
    )


_HKEX_2004_AUTHORITY = (
    "https://www.hkex.com.hk/News/News-Release/2004/040806news?sc_lang=en"
)
_HKEX_2005_AUTHORITY = (
    "https://www.hkex.com.hk/News/News-Release/2005/0506292news?sc_lang=en"
)
_HKEX_2006_AUTHORITY = (
    "https://www.hkex.com.hk/News/Regulatory-Announcements/2006/0607182news?sc_lang=en"
)
_HKEX_2025_2026_AUTHORITY = (
    "https://www.hkex.com.hk/Services/Trading/Securities/Overview/Trading-Mechanism/"
    "Reduction-of-Minimum-Spreads?sc_lang=en"
)


# Part A ordinary-security spread schedules.  The 2004 consultation records
# the then-current table on 6 August 2004; FR makes no correction before that
# evidenced boundary.  Later entries are effective dates stated by HKEX.
HKEX_PART_A_SPREAD_SCHEDULES: tuple[HKEXSpreadSchedule, ...] = (
    HKEXSpreadSchedule(
        "sehk_part_a_observed_2004_08_06", date(2004, 8, 6), _HKEX_2004_AUTHORITY,
        _spread_bands((
            ("0.01", "0.25", "0.001"), ("0.25", "0.50", "0.005"),
            ("0.50", "2.00", "0.010"), ("2.00", "5.00", "0.025"),
            ("5.00", "30.00", "0.050"), ("30.00", "50.00", "0.100"),
            ("50.00", "100.00", "0.250"), ("100.00", "200.00", "0.500"),
            ("200.00", "1000.00", "1.000"), ("1000.00", "9995.00", "2.500"),
        )),
    ),
    HKEXSpreadSchedule(
        "sehk_part_a_phase1_2005_07_04", date(2005, 7, 4), _HKEX_2005_AUTHORITY,
        _spread_bands((
            ("0.01", "0.25", "0.001"), ("0.25", "0.50", "0.005"),
            ("0.50", "2.00", "0.010"), ("2.00", "5.00", "0.025"),
            ("5.00", "30.00", "0.050"), ("30.00", "100.00", "0.050"),
            ("100.00", "200.00", "0.100"), ("200.00", "500.00", "0.200"),
            ("500.00", "1000.00", "0.500"), ("1000.00", "2000.00", "1.000"),
            ("2000.00", "5000.00", "2.000"), ("5000.00", "9995.00", "5.000"),
        )),
    ),
    HKEXSpreadSchedule(
        "sehk_part_a_phase2a_2006_07_24", date(2006, 7, 24), _HKEX_2006_AUTHORITY,
        _spread_bands((
            ("0.01", "0.25", "0.001"), ("0.25", "0.50", "0.005"),
            ("0.50", "2.00", "0.010"), ("2.00", "10.00", "0.010"),
            ("10.00", "20.00", "0.020"), ("20.00", "100.00", "0.050"),
            ("100.00", "200.00", "0.100"), ("200.00", "500.00", "0.200"),
            ("500.00", "1000.00", "0.500"), ("1000.00", "2000.00", "1.000"),
            ("2000.00", "5000.00", "2.000"), ("5000.00", "9995.00", "5.000"),
        )),
    ),
    HKEXSpreadSchedule(
        "sehk_part_a_reduction_phase1_2025_08_04", date(2025, 8, 4),
        _HKEX_2025_2026_AUTHORITY,
        _spread_bands((
            ("0.01", "0.25", "0.001"), ("0.25", "0.50", "0.005"),
            ("0.50", "10.00", "0.010"), ("10.00", "20.00", "0.010"),
            ("20.00", "50.00", "0.020"), ("50.00", "100.00", "0.050"),
            ("100.00", "200.00", "0.100"), ("200.00", "500.00", "0.200"),
            ("500.00", "1000.00", "0.500"), ("1000.00", "2000.00", "1.000"),
            ("2000.00", "5000.00", "2.000"), ("5000.00", "9995.00", "5.000"),
        )),
    ),
    HKEXSpreadSchedule(
        "sehk_part_a_reduction_phase2_2026_08_03", date(2026, 8, 3),
        _HKEX_2025_2026_AUTHORITY,
        _spread_bands((
            ("0.01", "0.25", "0.001"), ("0.25", "0.50", "0.005"),
            ("0.50", "10.00", "0.005"), ("10.00", "20.00", "0.010"),
            ("20.00", "50.00", "0.020"), ("50.00", "100.00", "0.050"),
            ("100.00", "200.00", "0.100"), ("200.00", "500.00", "0.200"),
            ("500.00", "1000.00", "0.500"), ("1000.00", "2000.00", "1.000"),
            ("2000.00", "5000.00", "2.000"), ("5000.00", "9995.00", "5.000"),
        )),
    ),
)


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _hkex_part_a_schedule(economic_time: str) -> HKEXSpreadSchedule | None:
    day = date.fromisoformat(economic_time)
    matches = [row for row in HKEX_PART_A_SPREAD_SCHEDULES if row.effective_from <= day]
    return matches[-1] if matches else None


def hkex_part_a_spread_schedule_id(economic_time: str) -> str | None:
    schedule = _hkex_part_a_schedule(economic_time)
    return schedule.schedule_id if schedule is not None else None


def canonical_hkex_unadjusted_price_text(value: Any, *, economic_time: str) -> str:
    """Remove only the proved Sina codec tail around an official HKEX price tick."""
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid HKEX price value: {value!r}") from exc
    if not decimal_value.is_finite():
        raise ValueError(f"invalid HKEX price value: {value!r}")
    try:
        schedule = _hkex_part_a_schedule(economic_time)
    except ValueError as exc:
        raise ValueError(f"invalid HKEX price economic_time: {economic_time!r}") from exc
    if schedule is None:
        return decimal_text(decimal_value)
    candidates: set[Decimal] = set()
    for band in schedule.bands:
        candidate = (
            (decimal_value / band.spread).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            * band.spread
        )
        if (
            band.contains(candidate)
            and decimal_value != candidate
            and abs(decimal_value - candidate) == SINA_HK_PRICE_CODEC_TAIL
        ):
            candidates.add(candidate)
    if len(candidates) == 1:
        decimal_value = candidates.pop()
    return decimal_text(decimal_value)


def mainland_share_type(exchange: str, code: str, explicit: str | None = None) -> str:
    """Return the exchange share class without using quote currency as identity."""
    venue = exchange.upper()
    if venue == "BSE":
        if explicit and explicit.upper() not in {"A", "BSE"}:
            raise ValueError("ordinary RMB BSE equity is A-share at the BSE venue")
        return "A"
    if explicit:
        return explicit.upper()
    text = str(code).zfill(6)
    if venue == "SSE" and text.startswith("9"):
        return "B"
    if venue == "SZSE" and text.startswith("2"):
        return "B"
    return "A"


def daily_metric_contract(
    *, exchange: str, code: str, share_type: str | None = None,
) -> dict[str, tuple[str, str, str, str, float, str, str]]:
    """Resolve the promotable Tencent daily contract for one mainland listing.

    Tencent's amount field is intentionally excluded for B shares.  Retained
    evidence proves the quote currencies (SSE B USD, SZSE B HKD), but does not
    establish one native amount currency/scale across venues and historical
    regimes.  The raw amount is preserved separately by
    :func:`daily_source_details`.
    """
    venue = exchange.upper()
    if venue == "HKEX":
        return {
            "equity.open": ("open", "daily_ohlc", "HKD/share", "HKD", 1.0, "currency_per_share", "HKD"),
            "equity.high": ("high", "daily_ohlc", "HKD/share", "HKD", 1.0, "currency_per_share", "HKD"),
            "equity.low": ("low", "daily_ohlc", "HKD/share", "HKD", 1.0, "currency_per_share", "HKD"),
            "equity.close": ("close", "daily_ohlc", "HKD/share", "HKD", 1.0, "currency_per_share", "HKD"),
            "market.volume": ("volume", "market_volume", "shares", "not_applicable", 1.0, "shares", "not_applicable"),
            "market.trade_amount": ("amount", "market_trade_amount", "HKD", "HKD", 1.0, "currency", "HKD"),
        }
    resolved_share_type = mainland_share_type(venue, code, share_type)
    if resolved_share_type == "B":
        if venue == "SSE":
            currency = "USD"
        elif venue == "SZSE":
            currency = "HKD"
        else:
            raise ValueError(f"unsupported Mainland B-share venue: {exchange}")
        result = dict(DAILY_METRIC_CONTRACT)
        for metric in ("equity.open", "equity.high", "equity.low", "equity.close"):
            field, family, _raw_unit, _raw_currency, scale, unit, _canonical_currency = result[metric]
            result[metric] = (field, family, f"{currency}/share", currency, scale, unit, currency)
        result.pop("market.trade_amount")
        return result
    return dict(DAILY_METRIC_CONTRACT)


@dataclass(frozen=True)
class DiscoveredListing:
    exchange: str
    code: str
    listing_date: str
    security_name: str
    source_record: Mapping[str, Any]


def _unwrap_jsonp(text: str) -> Any:
    stripped = text.strip()
    start = stripped.find("(")
    end = stripped.rfind(")")
    if start < 0 or end <= start:
        return json.loads(stripped)
    return json.loads(stripped[start + 1 : end])


def parse_bse_current_pages(page_texts: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for text in page_texts:
        payload = _unwrap_jsonp(text)
        containers = payload if isinstance(payload, list) else [payload]
        for container in containers:
            rows.extend(container.get("content", []))
    return rows


def parse_sse_current_payloads(payload_texts: Iterable[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for text in payload_texts:
        payload = json.loads(text)
        rows.extend(payload.get("result") or [])
    return rows


def parse_szse_current_workbook(payload: bytes) -> list[dict[str, Any]]:
    workbook = load_workbook(io.BytesIO(payload), read_only=False, data_only=True)
    sheet = workbook.active
    values = sheet.iter_rows(values_only=True)
    next(values)
    rows = []
    for values_row in values:
        if len(values_row) > 6 and values_row[4] is not None:
            rows.append({"A股代码": values_row[4], "A股简称": values_row[5], "A股上市日期": values_row[6]})
    return rows


def parse_szse_current_share_classes(payload: bytes) -> list[dict[str, Any]]:
    """Read current SZSE A- and B-share columns as separate listing rows.

    The public workbook is company-shaped and may expose the A and B counters
    on the same row.  Returning one record per non-empty counter preserves the
    listing/share-class boundary while keeping the legacy A-only parser stable
    for historical callers.
    """
    workbook = load_workbook(io.BytesIO(payload), read_only=False, data_only=True)
    values = workbook.active.iter_rows(values_only=True)
    header = next(values, None)
    if header is None:
        raise ValueError("SZSE current-stock workbook has no header")
    indexes = {re.sub(r"\s+", "", str(value or "")): index for index, value in enumerate(header)}
    required_a = {"A股代码", "A股简称", "A股上市日期"}
    if not required_a.issubset(indexes):
        raise ValueError("SZSE current-stock workbook lacks A-share columns")
    rows: list[dict[str, Any]] = []
    for values_row in values:
        for share_type in ("A", "B"):
            code_key = f"{share_type}股代码"
            name_key = f"{share_type}股简称"
            date_key = f"{share_type}股上市日期"
            if code_key not in indexes:
                continue
            code = values_row[indexes[code_key]] if indexes[code_key] < len(values_row) else None
            if code in (None, ""):
                continue
            name = values_row[indexes[name_key]] if name_key in indexes and indexes[name_key] < len(values_row) else None
            listing_date = values_row[indexes[date_key]] if date_key in indexes and indexes[date_key] < len(values_row) else None
            rows.append({
                "证券代码": code,
                "证券简称": name,
                "上市日期": listing_date,
                "share_type": share_type,
                code_key: code,
                name_key: name,
                date_key: listing_date,
            })
    return rows


def parse_szse_terminated_workbook(payload: bytes) -> list[dict[str, Any]]:
    """Read the exchange's four-column terminated-stock listing directory."""
    workbook = load_workbook(io.BytesIO(payload), read_only=False, data_only=True)
    values = workbook.active.iter_rows(values_only=True)
    header = next(values, None)
    if header is None or len(header) != 4:
        raise ValueError("SZSE terminated-stock workbook has no four-column header")
    rows = []
    for row in values:
        if len(row) != 4 or not row[0] or not row[2] or not row[3]:
            raise ValueError("SZSE terminated-stock workbook has an incomplete lifecycle row")
        rows.append({"证券代码": row[0], "证券简称": row[1],
                     "上市日期": row[2], "终止上市日期": row[3]})
    if not rows:
        raise ValueError("SZSE terminated-stock workbook has no lifecycle rows")
    return rows


def discover_bse_listings(
    page_texts: Iterable[str],
    *,
    baseline_episode_keys: set[str],
    cutoff_date: str,
) -> list[DiscoveredListing]:
    discovered: list[DiscoveredListing] = []
    for row in parse_bse_current_pages(page_texts):
        code = str(row.get("xxzqdm", "")).zfill(6)
        raw_date = str(row.get("fxssrq") or row.get("xxgprq") or "")
        if len(raw_date) != 8 or not raw_date.isdigit():
            continue
        listing_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        episode_key = f"BSE:{code}:{listing_date}:current"
        if listing_date <= cutoff_date or episode_key in baseline_episode_keys:
            continue
        discovered.append(
            DiscoveredListing(
                exchange="BSE",
                code=code,
                listing_date=listing_date,
                security_name=str(row.get("xxzqjc") or ""),
                source_record=row,
            )
        )
    return sorted(discovered, key=lambda row: (row.listing_date, row.code))


def parse_cninfo_subject_crosswalk(text: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(text)
    return {str(row["code"]).zfill(6): row for row in payload.get("stockList", [])}


def parse_tencent_daily_response(
    text: str,
    code: str,
    *,
    expected_adjustment_basis: str = "unadjusted",
    expected_jsonp_variable: str | None = None,
) -> list[dict[str, Any]]:
    source_text = text.strip()
    if source_text.startswith("{"):
        payload = json.loads(source_text)
    else:
        match = re.fullmatch(r"(kline_day[0-9]{4})\s*=\s*(\{.*\})\s*;?", source_text, re.DOTALL)
        if match is None or (expected_jsonp_variable is not None and match.group(1) != expected_jsonp_variable):
            raise ValueError("Tencent daily response has an unexpected JSONP wrapper")
        payload = json.loads(match.group(2))
    if not isinstance(payload, dict):
        raise ValueError("Tencent daily response must contain a JSON object")
    data = payload.get("data", {})
    symbol = next((key for key in data if key.lower().endswith(str(code).zfill(6))), None)
    if symbol is None:
        return []
    node = data[symbol]
    branches = [
        ("day", "unadjusted"),
        ("qfqday", "forward_adjusted"),
        ("hfqday", "backward_adjusted"),
    ]
    populated = [(name, basis, node.get(name)) for name, basis in branches if node.get(name)]
    if len(populated) > 1:
        raise ValueError(f"Tencent response contains multiple populated adjustment branches: {[row[0] for row in populated]}")
    if not populated:
        return []
    branch, actual_adjustment_basis, native_rows = populated[0]
    if actual_adjustment_basis != expected_adjustment_basis:
        raise ValueError(
            f"Tencent adjustment mismatch: expected {expected_adjustment_basis}, "
            f"returned {actual_adjustment_basis} in {branch}"
        )
    parsed = []
    for row in native_rows:
        if len(row) < 8:
            continue
        parsed.append(
            {
                "trade_date": row[0],
                "open": row[1],
                "close": row[2],
                "high": row[3],
                "low": row[4],
                "volume_lots": row[5],
                "trade_amount_reported": row[8] if len(row) > 8 and isinstance(row[6], dict) else row[6],
                # Compatibility alias only.  The name is not a semantic claim
                # for B-share responses and must not be used to promote them.
                "trade_amount_ten_thousand_cny": row[8] if len(row) > 8 and isinstance(row[6], dict) else row[6],
                "turnover_percent": row[7],
                "source_symbol": symbol,
                "source_branch": branch,
                "adjustment_basis": actual_adjustment_basis,
            }
        )
    return parsed


def daily_observations(
    native_rows: Iterable[Mapping[str, Any]],
    *,
    exchange: str,
    code: str,
    listing_id: str,
    source_response_hash: str,
    share_type: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    contracts = daily_metric_contract(exchange=exchange, code=code, share_type=share_type)
    for native in native_rows:
        for metric_id, contract in contracts.items():
            field, family, raw_unit, raw_currency, scale, unit, currency = contract
            raw_value = str(native[field])
            normalized = format(float(raw_value) * scale, ".12g")
            source_material = {
                "provider": "Tencent",
                "interface": "newfqkline",
                "exchange": exchange,
                "code": str(code).zfill(6),
                "listing_id": listing_id,
                "trade_date": native["trade_date"],
                "metric_id": metric_id,
                "field": field,
                "adjustment_basis": native["adjustment_basis"],
                "response_hash": source_response_hash,
            }
            result.append(
                {
                    "exchange": exchange,
                    "code": str(code).zfill(6),
                    "economic_time": native["trade_date"],
                    "metric_id": metric_id,
                    "series_family": family,
                    "raw_field": field,
                    "raw_value": raw_value,
                    "raw_unit": raw_unit,
                    "raw_currency": raw_currency,
                    "raw_scale": scale,
                    "normalized_value": normalized,
                    "canonical_unit": unit,
                    "canonical_currency": currency,
                    "source_provider": "Tencent",
                    "source_interface": "newfqkline",
                    "source_symbol": native.get("source_symbol"),
                    "source_branch": native.get("source_branch"),
                    "adjustment_basis": native["adjustment_basis"],
                    "source_response_hash": source_response_hash,
                    "source_observation_key": stable_key("source_observation", source_material),
                }
            )
    return result


def daily_source_details(
    native_rows: Iterable[Mapping[str, Any]],
    *,
    exchange: str,
    code: str,
    listing_id: str,
    source_response_hash: str,
    share_type: str | None = None,
) -> list[dict[str, Any]]:
    """Retain unresolved Tencent fields without promoting a standard fact."""
    if mainland_share_type(exchange, code, share_type) != "B":
        return []
    rows: list[dict[str, Any]] = []
    for native in native_rows:
        raw_value = native.get("trade_amount_reported")
        if raw_value in (None, ""):
            continue
        material = {
            "provider": "Tencent",
            "interface": "newfqkline",
            "exchange": exchange,
            "code": str(code).zfill(6),
            "listing_id": listing_id,
            "trade_date": native["trade_date"],
            "source_field": "field8",
            "response_hash": source_response_hash,
        }
        rows.append({
            "source_detail_key": stable_key("source_detail", material),
            "exchange": exchange,
            "code": str(code).zfill(6),
            "listing_id": listing_id,
            "economic_time": native["trade_date"],
            "source_provider": "Tencent",
            "source_interface": "newfqkline",
            "source_symbol": native.get("source_symbol"),
            "source_branch": native.get("source_branch"),
            "source_field": "field8",
            "raw_value": str(raw_value),
            "raw_unit": "provider_reported_amount",
            "raw_currency": "unresolved",
            "raw_scale": None,
            "adjustment_basis": native["adjustment_basis"],
            "source_response_hash": source_response_hash,
            "source_detail_semantic_state": "unresolved_native_amount_currency_and_scale",
            "promotion_status": "source_detail_only",
        })
    return rows


def parse_sina_financial_response(text: str) -> list[dict[str, Any]]:
    payload = json.loads(text)
    result = payload.get("result", {})
    data = result.get("data") if isinstance(result, dict) else None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        report_list = data.get("report_list")
        if isinstance(report_list, dict):
            flattened = []
            for period, report in report_list.items():
                for item in report.get("data", []):
                    flattened.append({**item, "REPORT_DATE": f"{period[:4]}-{period[4:6]}-{period[6:8]}"})
            return flattened
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


def financial_cash_begin_observation(
    rows: Iterable[Mapping[str, Any]],
    *,
    exchange: str,
    code: str,
    period_end: str,
    source_response_hash: str,
) -> dict[str, Any] | None:
    for row in rows:
        row_date = str(row.get("REPORT_DATE") or row.get("REPORTDATE") or row.get("报告期") or "")[:10]
        value = row.get("INICASHBALA")
        if value in (None, "") and row.get("item_field") == "INICASHBALA":
            value = row.get("item_value")
        if row_date != period_end or value in (None, ""):
            continue
        raw_value = str(value)
        material = {
            "provider": "Sina",
            "interface": "CompanyFinanceService.getFinanceReport2022",
            "exchange": exchange,
            "code": str(code).zfill(6),
            "period_end": period_end,
            "field": "INICASHBALA",
            "response_hash": source_response_hash,
        }
        provider_prefix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[exchange.upper()]
        return {
            "exchange": exchange,
            "code": str(code).zfill(6),
            "period_end": period_end,
            "metric_id": "financial.cash_and_cash_equivalents_begin",
            "normalized_value": raw_value,
            "canonical_unit": "currency",
            "canonical_currency": "CNY",
            "raw_value": raw_value,
            "raw_unit": "CNY_amount",
            "raw_currency": "CNY",
            "raw_scale": 1,
            "accounting_scope": "consolidated",
            "source_provider": "Sina",
            "source_interface": "CompanyFinanceService.getFinanceReport2022",
            "source_symbol": f"{provider_prefix}{str(code).zfill(6)}",
            "source_field_locator": "INICASHBALA",
            "source_response_hash": source_response_hash,
            "source_observation_key": stable_key("source_observation", material),
        }
    return None


# The continuing filing route implements the accepted A-share financial/KPI
# contract, not the complete metric registry.  ROE was retained as historical
# provenance during consolidation and is intentionally not promoted here.
ACCEPTED_A_SHARE_FINANCIAL_FIELDS: dict[str, tuple[str, str, str | None]] = {
    "financial.revenue": ("BIZINCO", "currency", "CNY"),
    "financial.total_operating_revenue": ("BIZTOTINCO", "currency", "CNY"),
    "financial.operating_profit": ("PERPROFIT", "currency", "CNY"),
    "financial.total_profit": ("TOTPROFIT", "currency", "CNY"),
    "financial.net_profit": ("NETPROFIT", "currency", "CNY"),
    "financial.parent_net_profit": ("PARENETP", "currency", "CNY"),
    "financial.eps": ("BASICEPS", "currency_per_share", "CNY"),
    "financial.total_current_assets": ("TOTCURRASSET", "currency", "CNY"),
    "financial.total_current_liabilities": ("TOTALCURRLIAB", "currency", "CNY"),
    "financial.total_assets": ("TOTASSET", "currency", "CNY"),
    "financial.total_liabilities": ("TOTLIAB", "currency", "CNY"),
    "financial.equity": ("RIGHAGGR", "currency", "CNY"),
    "financial.operating_cash_flow": ("MANANETR", "currency", "CNY"),
    "financial.investing_cash_flow": ("INVNETCASHFLOW", "currency", "CNY"),
    "financial.financing_cash_flow": ("FINNETCFLOW", "currency", "CNY"),
    "financial.cash_and_cash_equivalents_net_increase": ("CASHNETR", "currency", "CNY"),
    "financial.cash_and_cash_equivalents_begin": ("INICASHBALA", "currency", "CNY"),
    "financial.cash_and_cash_equivalents_end": ("FINALCASHBALA", "currency", "CNY"),
}

ACCEPTED_A_SHARE_FINANCIAL_METRICS = frozenset(
    {
        *ACCEPTED_A_SHARE_FINANCIAL_FIELDS,
        "financial.debt_ratio",
        "financial.net_margin",
        "financial.gross_margin",
    }
)


def _financial_row_value(row: Mapping[str, Any], field: str) -> Any:
    value = row.get(field)
    if value in (None, "") and row.get("item_field") == field:
        value = row.get("item_value")
    return value


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def financial_statement_observations(
    route_rows: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    exchange: str,
    code: str,
    period_end: str,
    source_response_hashes: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Map one filed reporting period to the accepted 21-metric contract.

    Statement fields retain their source route and response hash.  Ratios are
    derived only when all required source-native components are present and the
    denominator is non-zero; their provenance records the component fields and
    response hashes instead of pretending that the filing supplied a ratio.
    """
    matched: dict[str, tuple[list[Mapping[str, Any]], str]] = {}
    for route, rows in route_rows.items():
        period_rows = []
        for row in rows:
            row_date = str(row.get("REPORT_DATE") or row.get("REPORTDATE") or row.get("报告期") or "")[:10]
            if row_date == period_end:
                period_rows.append(row)
        if period_rows:
            matched[route] = (period_rows, source_response_hashes[route])

    def route_value(route: str, field: str) -> Any:
        for row in matched[route][0]:
            value = _financial_row_value(row, field)
            if value not in (None, ""):
                return value
        return None

    field_routes = {
        **{field: "lrb" for field in ("BIZINCO", "BIZTOTINCO", "BIZTOTCOST", "BIZCOST", "PERPROFIT", "TOTPROFIT", "NETPROFIT", "PARENETP", "BASICEPS")},
        **{field: "fzb" for field in ("TOTCURRASSET", "TOTALCURRLIAB", "TOTASSET", "TOTLIAB", "RIGHAGGR")},
        **{field: "llb" for field in ("MANANETR", "INVNETCASHFLOW", "FINNETCFLOW", "CASHNETR", "INICASHBALA", "FINALCASHBALA")},
    }
    prefix = {"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"}[exchange.upper()]
    observations: list[dict[str, Any]] = []
    values: dict[str, Decimal] = {}
    hashes_by_field: dict[str, str] = {}
    for metric_id, (field, unit, currency) in ACCEPTED_A_SHARE_FINANCIAL_FIELDS.items():
        route = field_routes[field]
        if route not in matched:
            continue
        _, response_hash = matched[route]
        raw = route_value(route, field)
        if raw in (None, ""):
            continue
        try:
            decimal_value = Decimal(str(raw))
        except InvalidOperation:
            continue
        values[field] = decimal_value
        hashes_by_field[field] = response_hash
        material = {
            "provider": "Sina",
            "interface": "CompanyFinanceService.getFinanceReport2022",
            "exchange": exchange.upper(),
            "code": str(code).zfill(6),
            "period_end": period_end,
            "field": field,
            "response_hash": response_hash,
        }
        observations.append({
            "exchange": exchange.upper(),
            "code": str(code).zfill(6),
            "period_end": period_end,
            "metric_id": metric_id,
            "normalized_value": _decimal_text(decimal_value),
            "canonical_unit": unit,
            "canonical_currency": currency,
            "raw_value": str(raw),
            "raw_unit": "CNY_amount" if unit == "currency" else "CNY_per_share",
            "raw_currency": "CNY",
            "raw_scale": 1,
            "accounting_scope": "consolidated",
            "source_provider": "Sina",
            "source_interface": "CompanyFinanceService.getFinanceReport2022",
            "source_symbol": f"{prefix}{str(code).zfill(6)}",
            "source_field_locator": field,
            "source_response_hash": response_hash,
            "source_observation_key": stable_key("source_observation", material),
            "normalization_evidence": "accepted source-native statement value at scale 1",
        })

    # Some accepted KPIs require statement components that are not themselves
    # members of the accepted metric contract (notably operating cost).
    for field in ("BIZCOST",):
        route = field_routes[field]
        if route not in matched:
            continue
        _, response_hash = matched[route]
        raw = route_value(route, field)
        if raw in (None, ""):
            continue
        try:
            values[field] = Decimal(str(raw))
        except InvalidOperation:
            continue
        hashes_by_field[field] = response_hash

    derived = {
        "financial.debt_ratio": ("TOTLIAB", "TOTASSET", "total liabilities / total assets"),
        "financial.net_margin": ("NETPROFIT", "BIZINCO", "net profit / revenue"),
        "financial.gross_margin": ("BIZINCO", "BIZCOST", "(revenue - operating cost) / revenue"),
    }
    for metric_id, (numerator_field, denominator_field, formula) in derived.items():
        if numerator_field not in values or denominator_field not in values or values[denominator_field] == 0:
            continue
        if metric_id == "financial.gross_margin":
            value = (values[numerator_field] - values[denominator_field]) / values[numerator_field]
        else:
            value = values[numerator_field] / values[denominator_field]
        component_hashes = sorted({hashes_by_field[numerator_field], hashes_by_field[denominator_field]})
        material = {
            "provider": "Sina",
            "interface": "CompanyFinanceService.getFinanceReport2022",
            "exchange": exchange.upper(),
            "code": str(code).zfill(6),
            "period_end": period_end,
            "metric": metric_id,
            "components": [numerator_field, denominator_field],
            "response_hashes": component_hashes,
        }
        observations.append({
            "exchange": exchange.upper(),
            "code": str(code).zfill(6),
            "period_end": period_end,
            "metric_id": metric_id,
            "normalized_value": _decimal_text(value),
            "canonical_unit": "decimal_ratio",
            "canonical_currency": "not_applicable",
            "raw_value": canonical_json({numerator_field: _decimal_text(values[numerator_field]), denominator_field: _decimal_text(values[denominator_field])}),
            "raw_unit": "derived_ratio_components",
            "raw_currency": "not_applicable",
            "raw_scale": 1,
            "accounting_scope": "consolidated",
            "source_provider": "Sina",
            "source_interface": "CompanyFinanceService.getFinanceReport2022",
            "source_symbol": f"{prefix}{str(code).zfill(6)}",
            "source_field_locator": f"derived:{metric_id}",
            "source_response_hash": stable_key("response_set", component_hashes).split(":", 1)[1],
            "source_observation_key": stable_key("source_observation", material),
            "normalization_evidence": f"derived from accepted source-native components: {formula}",
            "derived_component_fields": [numerator_field, denominator_field],
            "derived_component_response_hashes": component_hashes,
        })
    return sorted(observations, key=lambda row: row["metric_id"])


def parse_cninfo_documents(text: str, *, exchange: str, code: str, response_hash: str) -> list[dict[str, Any]]:
    payload = json.loads(text)
    rows = payload.get("announcements") or []
    result = []
    for row in rows:
        announcement_id = str(row.get("announcementId") or "")
        if not announcement_id:
            continue
        published_ms = row.get("announcementTime")
        published = date.fromtimestamp(int(published_ms) / 1000).isoformat() if published_ms else None
        result.append(
            {
                "exchange": exchange,
                "code": str(code).zfill(6),
                "effective_at": published,
                "announcement_id": announcement_id,
                "title": row.get("announcementTitle"),
                "source_url": "http://static.cninfo.com.cn/" + str(row.get("adjunctUrl") or "").lstrip("/"),
                "source_response_hash": response_hash,
                "source_observation_key": stable_key(
                    "source_observation",
                    {"provider": "CNINFO", "announcement_id": announcement_id, "response_hash": response_hash},
                ),
            }
        )
    return result


def derive_coverage_from_route_evidence(
    *,
    lifecycle_applicable: bool,
    route_attempt_status: str,
    returned_usable_observation_count: int,
    retained_source_contract_boundary: str | None = None,
) -> str:
    if not lifecycle_applicable:
        return "not_applicable"
    if returned_usable_observation_count > 0:
        return "available"
    if retained_source_contract_boundary:
        return "provider_no_yield"
    # Some retained route evidence predates the more explicit
    # ``success_empty``/``success_unusable`` split and records a successful
    # provider response even when this particular metric yielded no usable
    # rows.  Once the per-metric count is zero, that state has the same
    # coverage meaning as the explicit empty/unusable outcomes; accepting it
    # here keeps materialization compatible with the active route contract
    # without promoting an observation.
    if route_attempt_status in {"success", "success_empty", "success_unusable", "failure", "not_attempted"}:
        return "genuinely_missing"
    raise ValueError(f"unsupported route evidence state: {route_attempt_status}")


def require_internal_plan(plan: Mapping[str, Any]) -> None:
    forbidden = {"coverage_expectations", "authoritative_refresh"}
    present = sorted(forbidden.intersection(plan))
    if present:
        raise ValueError(f"pre-adjudicated external work-package fields are forbidden: {present}")
    if plan.get("schema_version") != "fr_a_share_discovery_acquisition_update_plan_v1":
        raise ValueError("continuing update requires an internally generated discovery/acquisition plan")


def discovered_listing_identity_decisions(*, entity_object_key: str, instrument_object_key: str,
        episode_object_key: str, exchange: str, share_type: str, provenance_refs: Iterable[str]) -> list[dict[str, Any]]:
    """Pure specifications for already accepted discoveries; no UUID allocation."""
    classification = mainland_share_type(exchange, episode_object_key.split(":")[1], share_type)
    if classification != mainland_share_type(exchange, episode_object_key.split(":")[1]):
        raise ValueError("authoritative share classification conflicts with venue/code contract")
    specifications = [
        ("entity", f"entity:{entity_object_key}", "legal_entity"),
        ("instrument", f"instrument:{instrument_object_key}", "ordinary_b_share_security" if classification == "B" else "ordinary_a_share_security"),
        ("listing", f"listing:{episode_object_key}", "exchange_listing_episode"),
        *[("series", f"series:{episode_object_key}:{family}", "listing_period_equity_daily_series")
          for family in ("daily_ohlc", "market_trade_amount", "market_turnover_rate", "market_volume")],
    ]
    return [{"subject_type": kind, "accepted_identity_statement": f"Accepted {economic_type} {key}",
             "economic_object_type": economic_type, "provenance_refs": list(provenance_refs),
             "decision_attributes": {"a_share_authoritative_owner_object_key": key,
                "authoritative_owner_schema": "fr_authoritative_a_share_lifecycle_owner_v1",
                "universe": "Equity", "region": "CN", "venue": exchange, "share_type": classification,
                "security_classification": "b_share" if classification == "B" else "a_share"}}
            for kind, key, economic_type in specifications]


def ensure_discovered_listing_identity(
    state: Any,
    *,
    entity_object_key: str,
    instrument_object_key: str,
    episode_object_key: str,
    provenance_refs: Iterable[str],
    exchange: str = "SSE",
    share_type: str = "A",
    existing_objects: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reuse or allocate the standard identity graph for an accepted discovery.

    Economic identity has already been decided by the authoritative discovery
    layer.  The durable owner allocates opaque installation-local UUIDs; public
    codes, names and provider records remain provenance rather than ID inputs.
    """
    specifications = discovered_listing_identity_decisions(entity_object_key=entity_object_key,
        instrument_object_key=instrument_object_key, episode_object_key=episode_object_key,
        exchange=exchange, share_type=share_type, provenance_refs=provenance_refs)
    existing = existing_objects if existing_objects is not None else {
        row.get("decision_attributes", {}).get("a_share_authoritative_owner_object_key"): row
        for row in state.rows()
    }
    missing = [row for row in specifications if row["decision_attributes"]["a_share_authoritative_owner_object_key"] not in existing]
    if missing:
        created = state.create_decisions_batch(missing)
        existing.update({row["decision_attributes"]["a_share_authoritative_owner_object_key"]: row for row in created})
    keys = [row["decision_attributes"]["a_share_authoritative_owner_object_key"] for row in specifications]
    objects = {key: existing[key] for key in keys}
    return {"objects": objects, "created_assignment_count": len(missing), "reused_assignment_count": len(specifications) - len(missing)}
