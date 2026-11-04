"""Official HKEX Equity population and listing-start source contracts.

This module parses exchange evidence only.  It does not infer economic
continuity from a code, and it deliberately labels annual report rows as
listing events rather than automatically turning every event into a new FR
listing episode.
"""

from __future__ import annotations

import io
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping

from bs4 import BeautifulSoup
from openpyxl import load_workbook

from backend.app.core.china_equity_identifiers import normalize_listing_code
from backend.app.core.china_equity_source_semantics import (
    canonical_hkex_unadjusted_price_text,
    decimal_text,
    hkex_part_a_spread_schedule_id,
)
from backend.app.core.artifact_io import stable_key


HKEX_SECURITIES_URL = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
HKEX_NEW_LISTING_PAGE = "https://www2.hkexnews.hk/new-listings/new-listing-information/main-board?sc_lang=en"
HKEX_NEWLY_LISTED_SECURITIES_URL = (
    "https://www.hkex.com.hk/Services/Trading/Securities/Trading-News/"
    "Newly-Listed-Securities?sc_lang=en"
)
HKEX_CURRENT_TRADING_ARRANGEMENTS_URL = (
    "https://www.hkex.com.hk/eng/market/sec_tradinfo/tradarng/tradarng_news/currentmonth/news.htm"
)
HKEX_PREVIOUS_TRADING_ARRANGEMENTS_URL = (
    "https://www.hkex.com.hk/eng/market/sec_tradinfo/tradarng/tradarng_news/premonth/news.htm"
)
HKEX_QUOTE_PAGE = "https://www.hkex.com.hk/Market-Data/Securities-Prices/Equities/Equities-Quote?sc_lang=en&sym={symbol}"
HKEX_QUOTE_API = "https://www1.hkex.com.hk/hkexwidget/data/getequityquote"
SINA_HK_SPOT_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHKStockData"
EASTMONEY_HK_SPOT_URL = "https://push2.eastmoney.com/api/qt/clist/get"

def load_provider_route_configuration() -> dict[str, Any]:
    """Load installation-local provider route permissions, if configured.

    Public adapters are intentionally entitlement-neutral: a URL being
    reachable is not permission to execute it as a default FR source.  A
    user may opt in through ``control/provider_route_config.json`` at the
    installation control root, or override its location with
    ``FR_PROVIDER_ROUTE_CONFIG``. Credentials and entitlements never belong
    in the repository or this return value.
    """
    configured = os.environ.get("FR_PROVIDER_ROUTE_CONFIG", "").strip()
    if configured:
        path = Path(configured)
    else:
        # Persisted installation configuration survives a fresh ordinary
        # process. Its absence still means no permission; never manufacture
        # enabled/rights values from adapter availability.
        from backend.app.core.storage_profile import resolve_control_plane_path
        path = resolve_control_plane_path().parent / "provider_route_config.json"
        if not path.is_file():
            return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"provider route configuration is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("provider route configuration must be a JSON object")
    return value


def hkex_public_provider_routes_enabled(configuration: Mapping[str, Any] | None = None) -> bool:
    """Return whether both public HKEX candidate adapters were explicitly enabled.

    The default is false.  ``enabled`` alone is insufficient unless a
    non-empty installation-local ``rights_basis`` is supplied, keeping the
    public release provider-capable without asserting public acquisition
    rights.  Retained replay and user imports do not use this gate.
    """
    value = dict(configuration) if configuration is not None else load_provider_route_configuration()
    routes = value.get("hkex_public_candidate_routes")
    if not isinstance(routes, Mapping):
        return False
    for provider in ("Sina", "Eastmoney"):
        route = routes.get(provider)
        if not isinstance(route, Mapping) or route.get("enabled") is not True:
            return False
        if not str(route.get("rights_basis") or "").strip():
            return False
    return True


def installation_provider_route_enabled(route_name: str, configuration: Mapping[str, Any] | None = None) -> bool:
    """Require explicit installation-local execution and rights for one adapter."""
    value = dict(configuration) if configuration is not None else load_provider_route_configuration()
    routes = value.get("provider_routes")
    route = routes.get(route_name) if isinstance(routes, Mapping) else None
    return (isinstance(route, Mapping) and route.get("enabled") is True
            and bool(str(route.get("rights_basis") or "").strip()))


def _text(value: Any) -> str:
    return str(value or "").strip()


def parse_sina_hk_spot_payload(payload: bytes | str, *, source_url: str = SINA_HK_SPOT_URL) -> list[dict[str, Any]]:
    """Parse the Sina executable HK current-candidate directory.

    The route is a provider inventory, not an exchange denominator.  Rows are
    therefore retained as candidates and carry the provider response locator;
    callers must reconcile them before allocating a FR identity.
    """
    text = payload.decode("utf-8", errors="strict") if isinstance(payload, bytes) else str(payload)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Sina HK spot response is not JSON") from exc
    if not isinstance(data, list):
        raise ValueError("Sina HK spot response is not a row array")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in data:
        if not isinstance(raw, Mapping):
            continue
        try:
            code = normalize_listing_code("HKEX", raw.get("symbol"))
        except ValueError:
            continue
        if code in seen:
            raise ValueError(f"Sina HK spot response contains duplicate code {code}")
        seen.add(code)
        result.append({
            "venue": "HKEX", "code": code,
            "display_name": _text(raw.get("name")) or code,
            "english_name": _text(raw.get("engname")) or None,
            "provider": "Sina", "source_url": source_url,
            "source_row": dict(raw),
        })
    return result


def parse_eastmoney_hk_spot_payload(payload: bytes | str, *, source_url: str = EASTMONEY_HK_SPOT_URL) -> list[dict[str, Any]]:
    """Parse Eastmoney's structured HK current-candidate list."""
    text = payload.decode("utf-8", errors="strict") if isinstance(payload, bytes) else str(payload)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Eastmoney HK spot response is not JSON") from exc
    rows = ((data.get("data") or {}).get("diff") if isinstance(data, Mapping) else None)
    if not isinstance(rows, list):
        raise ValueError("Eastmoney HK spot response lacks data.diff rows")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        try:
            code = normalize_listing_code("HKEX", raw.get("f12"))
        except ValueError:
            continue
        if code in seen:
            raise ValueError(f"Eastmoney HK spot response contains duplicate code {code}")
        seen.add(code)
        result.append({
            "venue": "HKEX", "code": code,
            "display_name": _text(raw.get("f14")) or code,
            "market_id": raw.get("f13"), "provider": "Eastmoney", "source_url": source_url,
            "source_row": dict(raw),
        })
    return result


def reconcile_hkex_provider_candidates(
    sina_rows: Iterable[Mapping[str, Any]], eastmoney_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Cross-check provider inventories without treating a code as identity.

    Exact code agreement across two independent provider inventories is an
    operational current candidate.  Special/temporary/rights-style labels are
    retained as explicit lifecycle candidates rather than silently promoted.
    The returned residuals are install-local gaps, not delisting conclusions.
    """
    sina = {str(row.get("code")): dict(row) for row in sina_rows}
    east = {str(row.get("code")): dict(row) for row in eastmoney_rows}
    rows: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    special = re.compile(r"(?:-OLD|-R(?:$|-)|-W(?:$|-)|RTS|DRS|权|旧|认股|涡轮|牛熊|\d[Kk]$)", re.IGNORECASE)
    for code in sorted(set(sina) | set(east)):
        left, right = sina.get(code), east.get(code)
        evidence = [row["source_url"] for row in (left, right) if row and row.get("source_url")]
        if left is None or right is None:
            residuals.append({
                "code": code, "reason": "provider_inventory_disagreement",
                "provider_presence": {"Sina": left is not None, "Eastmoney": right is not None},
                "evidence_refs": evidence,
            })
            continue
        names = {str(row.get("display_name") or "").strip() for row in (left, right)} - {""}
        identity_status = "provider_cross_checked_current_code_candidate"
        attribution = "provider_observation_episode_unresolved"
        if any(special.search(str(row.get("display_name") or "")) for row in (left, right)):
            identity_status = "provider_candidate_requires_lifecycle_evidence"
            attribution = "provider_candidate_episode_not_unique"
        rows.append({
            "venue": "HKEX", "code": code,
            "display_name": next(iter(names), code),
            "accepted_listing_id": None,
            "current_identity_resolution": identity_status,
            "observation_attribution": attribution,
            "listing_start": None, "listing_end": None,
            "listing_start_boundary": {"status": "unknown", "date": None},
            "provider_presence": {"Sina": True, "Eastmoney": True},
            "provider_evidence_refs": sorted(set(evidence)),
            "provider_name_match": len(names) <= 1,
            "source_rows": {"Sina": left.get("source_row"), "Eastmoney": right.get("source_row")},
        })
    return rows, residuals


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def parse_hkex_securities_workbook(payload: bytes) -> tuple[str, list[dict[str, Any]]]:
    workbook = load_workbook(io.BytesIO(payload), data_only=True, read_only=True)
    sheet = workbook.active
    sheet.reset_dimensions()
    rows = list(sheet.iter_rows(values_only=True))
    if len(rows) < 4:
        raise ValueError("HKEX List of Securities workbook is incomplete")
    updated_as_at = _text(rows[1][0]).replace("Updated as at", "").strip()
    headers = [_text(value) for value in rows[2]]
    required = {"Stock Code", "Name of Securities", "Category", "Sub-Category", "Trading Currency", "ISIN"}
    if not required.issubset(headers):
        raise ValueError("HKEX List of Securities schema changed")
    result: list[dict[str, Any]] = []
    for values in rows[3:]:
        raw = dict(zip(headers, values))
        if raw.get("Category") != "Equity" or raw.get("Stock Code") in (None, ""):
            continue
        code = normalize_listing_code("HKEX", raw["Stock Code"])
        result.append({
            "venue": "HKEX",
            "code": code,
            "display_name": _text(raw.get("Name of Securities")),
            "category": _text(raw.get("Category")),
            "sub_category": _text(raw.get("Sub-Category")),
            "trading_currency": _text(raw.get("Trading Currency")),
            "isin": _text(raw.get("ISIN")) or None,
            "board_lot": raw.get("Board Lot"),
            "rmb_counter": normalize_listing_code("HKEX", raw["RMB Counter"])
            if raw.get("RMB Counter") not in (None, "") else None,
            "updated_as_at": updated_as_at,
            "source_row": {key: raw.get(key) for key in headers if key},
        })
    if not result or len({row["code"] for row in result}) != len(result):
        raise ValueError("HKEX current Equity directory is empty or has duplicate codes")
    return updated_as_at, result


def decode_sina_hk_daily_payload(payload: bytes) -> list[dict[str, Any]]:
    """Decode one retained Sina HK unadjusted daily payload.

    The JavaScript decoder is supplied by the pinned AKShare dependency, but
    network acquisition remains owned by FR so the exact response can be
    hashed and retained before interpretation.
    """
    try:
        from akshare.stock.stock_hk_sina import hk_js_decode
        from py_mini_racer import MiniRacer

        encoded = payload.decode("utf-8", errors="strict").split("=", 1)[1].split(";", 1)[0].replace('"', "")
        decoder = MiniRacer()
        decoder.eval(hk_js_decode)
        native = decoder.call("d", encoded)
    except Exception as exc:
        raise ValueError("Sina HK daily payload decode failed") from exc
    rows: list[dict[str, Any]] = []
    for item in native:
        day = _text(item.get("date"))[:10]
        if not day:
            continue
        rows.append({
            "date": day,
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "volume": float(item["volume"]),
            "amount": float(item["amount"]),
        })
    return rows


def sina_hk_daily_observations(
    rows: Iterable[Mapping[str, Any]], *, code: str, listing_id: str, response_sha256: str,
    quote_currency: str = "HKD", supported_from: str | None = "0000-01-01",
    promote_amount: bool = True,
) -> list[dict[str, Any]]:
    """Normalize only a proved currency/time regime with usable OHLC values."""
    normalized_code = normalize_listing_code("HKEX", code)
    if quote_currency not in {"HKD", "USD"}:
        raise ValueError(f"unsupported HKEX Sina daily quote currency: {quote_currency}")
    contracts = {
        "equity.open": ("open", "daily_ohlc", "currency_per_share", quote_currency),
        "equity.high": ("high", "daily_ohlc", "currency_per_share", quote_currency),
        "equity.low": ("low", "daily_ohlc", "currency_per_share", quote_currency),
        "equity.close": ("close", "daily_ohlc", "currency_per_share", quote_currency),
        "market.volume": ("volume", "market_volume", "shares", "not_applicable"),
        "market.trade_amount": ("amount", "market_trade_amount", "currency", quote_currency),
    }
    if not promote_amount:
        contracts.pop("market.trade_amount")
    result: list[dict[str, Any]] = []
    for native in rows:
        day = _text(native["date"])[:10]
        if supported_from is None or day < supported_from or not _sina_hk_valid_ohlc(native):
            continue
        for metric_id, (field, family, unit, currency) in contracts.items():
            raw_value = str(native[field])
            if metric_id.startswith("equity."):
                normalized_value = canonical_hkex_unadjusted_price_text(
                    native[field], economic_time=day,
                )
            else:
                normalized_value = decimal_text(Decimal(raw_value))
            source_material = {
                "provider": "Sina", "interface": "hkstock_klc2_kl",
                "exchange": "HKEX", "code": normalized_code, "listing_id": listing_id,
                "trade_date": day, "metric_id": metric_id, "field": field,
                "adjustment_basis": "unadjusted", "response_hash": response_sha256,
            }
            result.append({
                "exchange": "HKEX", "code": normalized_code, "economic_time": day,
                "metric_id": metric_id, "series_family": family, "raw_field": field,
                "raw_value": raw_value, "raw_unit": unit,
                "raw_currency": currency, "raw_scale": 1.0,
                "normalized_value": normalized_value,
                "canonical_unit": unit, "canonical_currency": currency,
                "source_provider": "Sina", "source_interface": "hkstock_klc2_kl",
                "source_symbol": normalized_code, "source_branch": "unadjusted",
                "adjustment_basis": "unadjusted", "source_response_hash": response_sha256,
                "source_observation_key": stable_key("source_observation", source_material),
                "normalization_evidence": {
                    "policy": "sina_hk_unadjusted_price_precision_v1"
                    if metric_id.startswith("equity.") else "source_native_decimal_v1",
                    "source_value": raw_value,
                    "codec_tail_adjusted": normalized_value != decimal_text(Decimal(raw_value)),
                    "official_spread_schedule": (
                        hkex_part_a_spread_schedule_id(day)
                        if metric_id.startswith("equity.") else None
                    ),
                },
            })
    return result


def _sina_hk_valid_ohlc(native: Mapping[str, Any]) -> bool:
    try:
        opening, high, low, close = (float(native[field]) for field in ("open", "high", "low", "close"))
    except (KeyError, TypeError, ValueError):
        return False
    return min(opening, high, low, close) > 0 and low <= min(opening, close) <= max(opening, close) <= high


def sina_hk_daily_source_details(
    rows: Iterable[Mapping[str, Any]], *, code: str, listing_id: str,
    response_sha256: str, supported_from: str | None, promote_amount: bool,
) -> list[dict[str, Any]]:
    """Retain unsupported/zero-price Sina fields without fabricating facts."""
    normalized_code = normalize_listing_code("HKEX", code)
    result: list[dict[str, Any]] = []
    for native in rows:
        day = _text(native["date"])[:10]
        usable = supported_from is not None and day >= supported_from and _sina_hk_valid_ohlc(native)
        fields = ("amount",) if usable and not promote_amount else () if usable else (
            "open", "high", "low", "close", "volume", "amount"
        )
        for field in fields:
            result.append({
                "source_detail_key": stable_key("source_detail", {
                    "provider": "Sina", "interface": "hkstock_klc2_kl", "code": normalized_code,
                    "listing_id": listing_id, "date": day, "field": field,
                    "response_sha256": response_sha256,
                }),
                "exchange": "HKEX", "code": normalized_code, "listing_id": listing_id,
                "economic_time": day, "metric_id": {
                    "open": "equity.open", "high": "equity.high", "low": "equity.low",
                    "close": "equity.close", "volume": "market.volume", "amount": "market.trade_amount",
                }[field],
                "source_provider": "Sina", "source_interface": "hkstock_klc2_kl",
                "source_symbol": normalized_code, "source_branch": "unadjusted",
                "source_field": field, "raw_value": str(native[field]),
                "raw_unit": "provider_reported", "raw_currency": "unresolved",
                "raw_scale": None, "adjustment_basis": "unadjusted",
                "source_response_hash": response_sha256,
                "source_detail_semantic_state": "unproved_currency_or_unusable_ohlc" if not usable else "unproved_native_amount_scale",
                "promotion_status": "source_detail_only",
            })
    return result


def new_listing_report_links(page_html: str, *, base_url: str = HKEX_NEW_LISTING_PAGE) -> list[dict[str, str]]:
    from urllib.parse import urljoin

    soup = BeautifulSoup(page_html, "html.parser")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href or "New-Listing-Report/" not in href or not href.lower().endswith((".xls", ".xlsx")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        board = "GEM" if "/GEM/" in href else "MAIN_BOARD"
        match = re.search(r"(19|20)\d{2}", href)
        year = match.group(0) if match else "unknown"
        rows.append({"board": board, "report_year": year, "url": url, "filename": href.rsplit("/", 1)[-1]})
    return sorted(rows, key=lambda row: (row["board"], row["report_year"], row["url"]))


def _workbook_rows(payload: bytes) -> tuple[list[list[Any]], int]:
    if payload.startswith(b"PK"):
        workbook = load_workbook(io.BytesIO(payload), data_only=True, read_only=True)
        return [list(row) for row in workbook.active.iter_rows(values_only=True)], 0
    try:
        import xlrd
    except ImportError as exc:  # pragma: no cover - exercised by distribution validation
        raise RuntimeError("legacy HKEX .xls reports require xlrd") from exc
    workbook = xlrd.open_workbook(file_contents=payload)
    sheet = workbook.sheet_by_index(0)
    return [sheet.row_values(index) for index in range(sheet.nrows)], int(workbook.datemode)


def _excel_date(value: Any, datemode: int) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and 20_000 < float(value) < 80_000:
        # Excel's 1900 system includes the historical leap-year bug.
        base = date(1899, 12, 30) if datemode == 0 else date(1904, 1, 1)
        return (base + timedelta(days=int(float(value)))).isoformat()
    text = _text(value).replace(".", "/").replace("-", "/")
    for pattern in ("%d/%m/%Y", "%d/%m/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:10], pattern).date().isoformat()
        except ValueError:
            continue
    return None


def parse_new_listing_report(
    payload: bytes, *, board: str, report_year: str, source_url: str,
) -> list[dict[str, Any]]:
    matrix, datemode = _workbook_rows(payload)
    result: list[dict[str, Any]] = []
    for raw in matrix:
        if len(raw) < 5:
            continue
        code_value = raw[1]
        if code_value in (None, "", '"'):
            continue
        try:
            code = normalize_listing_code("HKEX", code_value)
        except ValueError:
            continue
        date_value = raw[4] if board == "MAIN_BOARD" else raw[0]
        listing_date = _excel_date(date_value, datemode)
        if listing_date is None:
            continue
        joined = " | ".join(_text(value) for value in raw if value not in (None, ""))
        transfer = "transfer of listing" in joined.lower()
        result.append({
            "venue": "HKEX",
            "code": code,
            "company_name_at_event": _text(raw[2]),
            "event_date": listing_date,
            "event_type": "board_transfer" if transfer else "new_listing_candidate",
            "board": board,
            "report_year": report_year,
            "source_url": source_url,
            "source_row": [_json_value(value) for value in raw],
        })
    return result


def parse_newly_listed_securities_html(
    page_html: str, *, source_url: str = HKEX_NEWLY_LISTED_SECURITIES_URL,
) -> list[dict[str, Any]]:
    """Parse the bounded HKEX newly-listed/traded security table.

    The exchange publishes new listings and temporary/corporate-action
    counters in the same table.  This parser preserves the reason and base
    code as evidence; it does not turn every row into a new economic episode.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 8:
            continue
        try:
            code = normalize_listing_code("HKEX", cells[2])
        except ValueError:
            continue
        former_code = None
        if cells[-1]:
            try:
                former_code = normalize_listing_code("HKEX", cells[-1])
            except ValueError:
                former_code = None
        rows.append({
            "date": _excel_date(cells[0], 0),
            "name": cells[1],
            "code": code,
            "board_lot": cells[3] if len(cells) > 3 else None,
            "reason": cells[-2],
            "former_or_base_code": former_code,
            "source_url": source_url,
            "source_row": cells,
        })
    return rows


def parse_trading_arrangements_html(
    page_html: str, *, source_url: str,
) -> list[dict[str, Any]]:
    """Parse an official current/previous-month trading-arrangement page."""
    soup = BeautifulSoup(page_html, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        code_index = next(
            (index for index, cell in enumerate(cells) if re.fullmatch(r"\d{5}", cell.replace(" ", ""))),
            None,
        )
        if code_index is None:
            continue
        try:
            code = normalize_listing_code("HKEX", cells[code_index])
        except ValueError:
            continue
        rows.append({
            "notice_date": _excel_date(cells[0], 0),
            "code": code,
            "name": cells[code_index + 1] if len(cells) > code_index + 1 else "",
            "description": " | ".join(cells[code_index + 2:]).strip(),
            "source_url": source_url,
            "source_row": cells,
        })
    return rows


def quote_token(page_html: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    for script in soup.find_all("script"):
        body = script.string or script.get_text(" ", strip=False)
        for token in re.findall(r'(?m)^\s*return\s+"([^"\r\n]+)"', body or ""):
            if len(token) >= 32:
                # HKEX embeds the token percent-escaped in the page.  Requests
                # performs query-string escaping, so return the decoded token
                # here to avoid turning ``%2B`` into ``%252B``.
                return unquote(token)
    raise ValueError("HKEX quote page did not expose its session token")


def parse_quote_jsonp(text: str) -> dict[str, Any]:
    start, end = text.find("("), text.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("HKEX quote response is not JSONP")
    payload = json.loads(text[start + 1:end])
    data = payload.get("data") or {}
    if str(data.get("responsecode")) != "000" or not isinstance(data.get("quote"), Mapping):
        raise ValueError(f"HKEX quote response failed: {data.get('responsecode')}/{data.get('responsemsg')}")
    quote = dict(data["quote"])
    code = normalize_listing_code("HKEX", quote.get("sym"))
    def quote_date(value: Any) -> str | None:
        raw = _text(value)
        for pattern in ("%d %b %Y", "%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw, pattern).date().isoformat()
            except ValueError:
                continue
        return None
    return {
        "code": code,
        "listing_date": quote_date(quote.get("listing_date")),
        "transfer_of_listing_date": quote_date(quote.get("transfer_of_listing_date")),
        "name": _text(quote.get("nm") or quote.get("nm_s")),
        "isin": _text(quote.get("isin")) or None,
        "trading_currency": _text(quote.get("ccy")) or None,
        "product_type": _text(quote.get("product_type")),
        "product_subtype": _text(quote.get("product_subtype")) or None,
        "listing_category": _text(quote.get("listing_category")) or None,
        "multiple_counter": list(quote.get("multiple_counter") or []),
        "source_record": quote,
    }


def current_economic_population_from_reference(
    current_rows: Iterable[Mapping[str, Any]], reference_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Bind a live exchange directory to the accepted economic-row treatment.

    New or changed rows are returned as residuals; they are never classified by
    code/name heuristics.  This preserves the accepted population owner while
    allowing online reconciliation at install/update time.
    """
    reference = {str(row["code"]): dict(row) for row in reference_rows}
    current = {str(row["code"]): dict(row) for row in current_rows}
    accepted: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    for code, row in sorted(current.items()):
        prior = reference.get(code)
        if prior is None:
            residuals.append({"code": code, "reason": "new_exchange_row_not_in_release_reference", "current": row})
            continue
        expected = {
            "name": _text(prior.get("name")),
            "isin": _text(prior.get("isin")) or None,
            "currency": _text(prior.get("currency")),
        }
        actual = {
            "name": _text(row.get("display_name")),
            "isin": _text(row.get("isin")) or None,
            "currency": _text(row.get("trading_currency")),
        }
        if expected != actual:
            residuals.append({"code": code, "reason": "current_exchange_row_changed_from_release_reference", "expected": expected, "actual": actual})
            continue
        if bool(prior.get("counts_as_current_economic_security")):
            accepted.append({**row, "accepted_reference": prior})
    for code, prior in sorted(reference.items()):
        if code not in current and bool(prior.get("counts_as_current_economic_security")):
            residuals.append({"code": code, "reason": "release_reference_economic_security_absent_from_current_exchange_directory", "reference": prior})
    return accepted, residuals


def reclassify_unknown_current_listing_starts(
    reference_rows: Iterable[Mapping[str, Any]],
    accepted_lifecycle_rows: Iterable[Mapping[str, Any]],
    historical_lifecycle_rows: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep a missing exact date separate from economic identity and attribution.

    The accepted lifecycle graph, not a provider's first price or a compiled
    third-party date, owns the episode check.  A competing same-code episode
    remains a residual even when the current security itself is identified.
    """
    by_code: dict[str, list[Mapping[str, Any]]] = {}
    historical_codes: set[str] = set()
    for row in accepted_lifecycle_rows:
        by_code.setdefault(str(row.get("code") or ""), []).append(row)
    for row in historical_lifecycle_rows:
        historical_codes.add(str(row.get("code") or ""))
    classified: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    for original in reference_rows:
        row = dict(original)
        if not row.get("counts_as_current_economic_security"):
            classified.append(row)
            continue
        if row.get("listing_start"):
            # An actual authoritative date already encodes the exact case;
            # avoid inflating every stable reference row with redundant fields.
            row.pop("listing_start_boundary", None)
            row.pop("current_identity_resolution", None)
            classified.append(row)
            continue
        code = str(row.get("code") or "")
        candidates = by_code.get(code, [])
        matches = [
            candidate for candidate in candidates
            if candidate.get("denominator_side") == "current"
            and candidate.get("active_state") == "current"
            and candidate.get("isin") == row.get("isin")
            and candidate.get("accepted_listing_id")
        ]
        competing = len(candidates) != 1 or code in historical_codes
        unresolved = any(candidate.get("unresolved_lifecycle_facts") or candidate.get("event_chain") for candidate in matches)
        if len(matches) != 1 or competing or unresolved:
            reason = "competing_or_unresolved_listing_episode" if competing or unresolved else "accepted_identity_graph_match_missing"
            row["listing_start_boundary"] = {"status": "unknown", "date": None}
            row["observation_attribution"] = "blocked_competing_or_unresolved_episode"
            row["listing_start_resolution"] = "lifecycle_boundary_residual"
            residuals.append({"code": code, "isin": row.get("isin"), "reason": reason,
                              "accepted_graph_matches": len(matches), "same_code_graph_rows": len(candidates),
                              "same_code_historical_rows": int(code in historical_codes)})
        else:
            match = matches[0]
            row["accepted_listing_id"] = match["accepted_listing_id"]
            row["accepted_identity_evidence_refs"] = sorted({
                str(source["source_url"]) for source in match.get("hkexnews_active_matches") or []
                if source.get("source_url")
            })
            row["current_identity_resolution"] = "accepted_current_economic_security"
            row["listing_start_boundary"] = {"status": "unknown", "date": None}
            row["observation_attribution"] = "unique_current_episode_in_accepted_graph"
            row["listing_start_resolution"] = "exact_date_unknown_identity_resolved"
        classified.append(row)
    return classified, residuals
