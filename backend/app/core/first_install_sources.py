"""Source-driven live acquisition for the first-install population.

Executable provider inventories are enumerated for current and bounded
historical requests, while explicit selections remain available for targeted
runs. Exact public responses are retained and the normalized package consumed
by ``first_install_bootstrap`` records unresolved identity or availability as
gaps. It never treats source observations as an absolute market denominator.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import requests

from backend.app.core.china_equity_source_semantics import (
    daily_observations, daily_source_details, mainland_share_type,
    parse_bse_current_pages, parse_szse_current_share_classes,
    parse_szse_terminated_workbook, parse_tencent_daily_response,
)
from backend.app.core.artifact_io import canonical_json, stable_key, utc_now, write_json_atomic
from backend.app.core.source_transport import retain_bytes_once, sha256_bytes
from backend.app.core.china_equity_identifiers import normalize_listing_code
from backend.app.core.hkex_equity_sources import (
    EASTMONEY_HK_SPOT_URL,
    HKEX_SECURITIES_URL,
    SINA_HK_SPOT_URL,
    current_economic_population_from_reference,
    decode_sina_hk_daily_payload,
    parse_hkex_securities_workbook,
    hkex_public_provider_routes_enabled,
    load_provider_route_configuration,
    sina_hk_daily_observations,
    sina_hk_daily_source_details,
)
from backend.app.core.china_public_fund_update import FundIdentityReviewRequired, PublicFundSourceClient
from backend.app.core.desired_data_profile import DesiredDataProfile
from backend.app.core.first_install_bootstrap import SOURCE_PACKAGE_SCHEMA, load_source_contract


class FirstInstallSourceError(RuntimeError):
    pass


class HKEXIdentityReferenceGap(FirstInstallSourceError):
    """No installation-owned accepted HKEX population reference is available."""


HKEX_REFERENCE_PATH = Path(__file__).resolve().parents[3] / "config" / "fr_hkex_equity_population_reference_v1.json"


def _load_hkex_reference() -> dict[str, Any]:
    # The internal accepted population file is deliberately absent from the
    # public source package. An official directory alone cannot settle identity.
    try:
        reference = json.loads(HKEX_REFERENCE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HKEXIdentityReferenceGap(
            "identity_reference_gap: HKEX first install requires a separately accepted installation-owned identity reference"
        ) from exc
    if (not isinstance(reference, dict)
            or reference.get("schema_version") != "fr_hkex_equity_population_reference_v1"
            or not isinstance(reference.get("rows"), list)
            or not reference["rows"]):
        raise HKEXIdentityReferenceGap(
            "identity_reference_gap: HKEX identity reference has no supported nonempty population contract"
        )
    # Check the existing release-reference row shape before any source call.
    # This does not decide whether the installation's financial evidence is
    # accepted; non-economic/residual rows remain valid reference entries.
    seen_codes: set[str] = set()
    usable_accepted_rows = 0
    for index, row in enumerate(reference["rows"]):
        if not isinstance(row, dict):
            raise HKEXIdentityReferenceGap(
                f"identity_reference_gap: HKEX reference row {index} is not an object"
            )
        code = row.get("code")
        if (not isinstance(code, str) or len(code) != 5 or not code.isdigit()
                or code in seen_codes):
            raise HKEXIdentityReferenceGap(
                f"identity_reference_gap: HKEX reference row {index} has no unique canonical code"
            )
        seen_codes.add(code)
        for field in ("name", "currency", "classification",
                      "economic_security_group_key", "fr_identity_treatment"):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                raise HKEXIdentityReferenceGap(
                    f"identity_reference_gap: HKEX reference row {index} lacks {field}"
                )
        accepted = row.get("counts_as_current_economic_security")
        if type(accepted) is not bool:
            raise HKEXIdentityReferenceGap(
                f"identity_reference_gap: HKEX reference row {index} lacks an economic-row decision"
            )
        start = row.get("listing_start")
        accepted_id = row.get("accepted_listing_id")
        has_start = isinstance(start, str) and bool(start.strip())
        has_attributed_id = (isinstance(accepted_id, str) and bool(accepted_id.strip())
                             and row.get("observation_attribution") == "unique_current_episode_in_accepted_graph")
        if accepted and (has_start or has_attributed_id):
            usable_accepted_rows += 1
    if not usable_accepted_rows:
        raise HKEXIdentityReferenceGap(
            "identity_reference_gap: HKEX reference has no usable accepted economic-identity row"
        )
    return reference


def _profile_requests_hkex(profile: DesiredDataProfile, contract: Mapping[str, Any]) -> bool:
    for scope in profile.scopes:
        if scope.state != "enabled" or scope.universe != "CN_A_SHARE":
            continue
        if scope.population_mode == "explicit_selection":
            if any(str(item.get("venue") or "").upper() == "HKEX"
                   for item in scope.population_spec["selectors"]):
                return True
        else:
            venues = scope.population_spec.get("venues") or contract["universes"][scope.universe]["bootstrap_executable_venues"]
            if "HKEX" in {str(venue).upper() for venue in venues}:
                return True
    return False


def _date_text(value: Any) -> str:
    if isinstance(value, (int, float)) and float(value).is_integer():
        value = str(int(value))
    text = str(value or "").strip().replace("/", "-")
    if text in {"-", "--", "nan", "NaT", "None"}:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def _code_text(value: Any, *, venue: str | None = None) -> str:
    if venue:
        try:
            return normalize_listing_code(venue, value)
        except ValueError as exc:
            raise FirstInstallSourceError(str(exc)) from exc
    if isinstance(value, (int, float)) and float(value).is_integer():
        value = str(int(value))
    code = str(value or "").strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise FirstInstallSourceError(f"invalid six-digit listing code: {value!r}")
    return code


def _display_text(*values: Any, fallback: str) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text not in {"-", "--", "nan", "None"}:
            return text
    return fallback


class FirstInstallSourceAcquirer:
    """Public-source adapter with immutable receipts and no installed-state reads."""

    def __init__(
        self, root: Path, *, session: requests.Session | None = None, timeout: int = 90,
        provider_configuration: Mapping[str, Any] | None = None,
    ):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.timeout = timeout
        self.provider_configuration = dict(provider_configuration) if provider_configuration is not None else load_provider_route_configuration()
        self.receipts: list[dict[str, Any]] = []

    def _get(
        self, source_id: str, url: str, *, params: Mapping[str, Any], referer: str | None = None,
        method: str = "GET", data: Mapping[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        headers = {"User-Agent": "Mozilla/5.0 FinancialResearch first-install bootstrap"}
        if referer:
            headers["Referer"] = referer
        if method.upper() == "GET" and data is None:
            response = self.session.get(url, params=dict(params), headers=headers, timeout=self.timeout)
        else:
            response = self.session.request(method, url, params=dict(params), data=dict(data or {}), headers=headers, timeout=self.timeout)
        response.raise_for_status()
        payload = response.content
        digest = sha256_bytes(payload)
        target = self.root / "raw" / f"{source_id}_{digest[:16]}.bin"
        retain_bytes_once(self.root, Path("raw") / target.name, payload, conflict_error=FirstInstallSourceError)
        self.receipts.append({
            "source_id": source_id, "url": response.url, "http_status": response.status_code,
            "response_bytes": len(payload), "response_sha256": digest,
            "retained_response_path": str(target), "acquired_at_utc": utc_now(),
        })
        return payload, response.url

    def _sse_equity_episode(self, code: str, listing_start: str | None) -> tuple[dict[str, Any], str]:
        base = {
            "REG_PROVINCE": "", "CSRC_CODE": "", "STOCK_CODE": code,
            "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L", "type": "inParams",
            "isPagination": "true", "pageHelp.cacheSize": "1", "pageHelp.beginPage": "1",
            "pageHelp.pageSize": "1000", "pageHelp.pageNo": "1", "pageHelp.endPage": "1",
        }
        share_type = "B" if code.startswith("9") else "A"
        candidates: list[tuple[dict[str, Any], str]] = []
        for status, label, referer in (
            ("2,4,5,7,8", "current", "https://www.sse.com.cn/assortment/stock/list/share/"),
            ("3", "terminated", "https://www.sse.com.cn/assortment/stock/list/delisting/"),
        ):
            raw, url = self._get(
                f"sse_equity_{label}_{share_type.lower()}_{code}", "https://query.sse.com.cn/sseQuery/commonQuery.do",
                params={**base, "COMPANY_STATUS": status, "STOCK_TYPE": "2" if share_type == "B" else "1,8"}, referer=referer,
            )
            payload = json.loads(raw.decode("gbk", errors="replace"))
            rows = payload.get("result")
            if not isinstance(rows, list):
                raise FirstInstallSourceError("SSE listing response lacks result rows")
            for row in rows:
                row_code_value = row.get("B_STOCK_CODE") if share_type == "B" else (row.get("A_STOCK_CODE") or row.get("COMPANY_CODE"))
                row_code = str(row_code_value or "").zfill(6)
                if row_code == code and (not listing_start or _date_text(row.get("LIST_DATE")) == listing_start):
                    candidates.append((dict(row), url))
        if len(candidates) != 1:
            raise FirstInstallSourceError(f"SSE {code}/{listing_start or 'unresolved'} did not resolve to one listing episode")
        return candidates[0]

    def _sse_equity_daily(
        self, code: str, start: str, end: str, *, venue: str = "SSE",
    ) -> tuple[list[dict[str, Any]], str, str]:
        symbol = f"{'sh' if venue == 'SSE' else 'sz' if venue == 'SZSE' else 'bj'}{code}"
        raw, url = self._get(
            f"tencent_equity_daily_{code}",
            "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get",
            params={
                "param": f"{symbol},day,{start},{end},640,",
                "_var": f"kline_day{end[:4]}",
                "r": "0.8205512681390605",
            },
        )
        text = raw.decode("utf-8", errors="replace")
        parsed = parse_tencent_daily_response(
            text, code, expected_adjustment_basis="unadjusted",
            expected_jsonp_variable=f"kline_day{end[:4]}",
        )
        return parsed, hashlib.sha256(raw).hexdigest(), url

    def _bse_equity_population(self) -> list[dict[str, Any]]:
        """Enumerate the current BSE directory with the accepted JSONP route."""
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for page in range(100):
            raw, url = self._get(
                f"bse_equity_current_page_{page}",
                "https://www.bse.cn/nqxxController/nqxxCnzq.do",
                params={}, method="POST", data={"page": str(page), "typejb": "T", "xxfcbj[]": "2", "xxzqdm": "", "sortfield": "xxzqdm", "sorttype": "asc"},
                referer="https://www.bse.cn/nq/listedcompany.html",
            )
            # The BSE route is a POST form endpoint; requests.Session accepts
            # the same payload through params for GET-compatible mirrors only.
            # If the public endpoint rejects it, the explicit source gap is
            # preserved rather than inventing a population.
            # The public endpoint advertises UTF-8 but currently emits legacy
            # GBK bytes for Chinese display fields.  Decode the payload using
            # the observed source encoding so names remain usable evidence;
            # malformed bytes stay replacement characters and never affect
            # code/date identity fields.
            page_rows = parse_bse_current_pages([raw.decode("gbk", errors="replace")])
            page_codes = {str(row.get("xxzqdm") or "").zfill(6) for row in page_rows if row.get("xxzqdm")}
            if not page_codes or page_codes.issubset(seen):
                break
            seen.update(page_codes)
            for row in page_rows:
                code = str(row.get("xxzqdm") or "").zfill(6)
                raw_date = str(row.get("fxssrq") or row.get("xxgprq") or "")
                listing_start = _date_text(raw_date)
                if len(code) != 6 or not listing_start:
                    continue
                rows.append({
                    "venue": "BSE", "code": code, "listing_start": listing_start, "listing_end": None,
                    "display_name": _display_text(row.get("xxzqjc"), fallback=code),
                    "board": "BSE", "share_type": "A", "evidence_refs": [url], "source_row": row,
                })
        if not rows:
            raise FirstInstallSourceError("BSE current Equity directory returned no usable rows")
        if len({(row["venue"], row["code"]) for row in rows}) != len(rows):
            raise FirstInstallSourceError("BSE current Equity directory contains duplicate exchange/code rows")
        return rows

    def _hkex_equity_population(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        """Bind the live official directory to accepted economic identities.

        Provider inventories are not an authority for this current population;
        daily provider configuration is checked separately during acquisition.
        """
        reference = _load_hkex_reference()
        payload, official_url = self._get("hkex_current_equity", HKEX_SECURITIES_URL, params={})
        _updated_at, official_rows = parse_hkex_securities_workbook(payload)
        accepted, official_residuals = current_economic_population_from_reference(official_rows, reference["rows"])
        rows: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        for current in accepted:
            prior = dict(current["accepted_reference"])
            start = prior.get("listing_start")
            accepted_id = prior.get("accepted_listing_id")
            attribution = prior.get("observation_attribution")
            if not start and (not accepted_id or attribution != "unique_current_episode_in_accepted_graph"):
                gaps.append({
                    "gap_type": "identity_blocked", "universe": "CN_A_SHARE", "venue": "HKEX",
                    "code": current["code"], "population_role": "accepted_identity_lifecycle_attribution_unresolved",
                    "reason": "unknown listing start requires a unique accepted episode",
                    "promoted_fact_count": 0, "evidence_refs": [official_url, *prior.get("accepted_identity_evidence_refs", [])],
                })
                continue
            rows.append({
                "venue": "HKEX", "code": current["code"], "listing_start": start,
                "listing_end": None, "display_name": current["display_name"],
                "board": prior.get("sub_category") or "HKEX Equity", "share_type": "HKEX_EQUITY",
                "trading_currency": current.get("trading_currency"),
                "accepted_listing_id": accepted_id,
                "current_identity_resolution": "accepted_current_economic_security",
                "listing_start_boundary": prior.get("listing_start_boundary") or {"status": "exact" if start else "unknown", "date": start},
                "observation_attribution": attribution or ("unique_current_episode_in_accepted_graph" if start else None),
                "daily_source_contract": prior.get("daily_source_contract"),
                "evidence_refs": [official_url, *prior.get("accepted_identity_evidence_refs", []),
                                  "config/fr_hkex_equity_population_reference_v1.json"],
            })
        for residual in official_residuals:
            gaps.append({
                "gap_type": "identity_blocked", "universe": "CN_A_SHARE", "venue": "HKEX",
                "code": residual["code"], "population_role": "official_hkex_reference_reconciliation_residual",
                "reason": residual["reason"], "promoted_fact_count": 0,
                "evidence_refs": [official_url, "config/fr_hkex_equity_population_reference_v1.json"],
            })
        return rows, gaps, len(official_rows)

    def _hkex_equity_daily(
        self, code: str, start: str, end: str,
    ) -> tuple[list[dict[str, Any]], str, str]:
        """Retain and decode the accepted Sina unadjusted HK daily payload."""
        url = f"https://finance.sina.com.cn/stock/hkstock/{code}/klc2_kl.js"
        raw, final_url = self._get(f"sina_hk_equity_daily_{code}", url, params={})
        try:
            native = decode_sina_hk_daily_payload(raw)
        except ValueError as exc:
            raise FirstInstallSourceError(f"Sina HK daily payload decode failed for {code}") from exc
        rows: list[dict[str, Any]] = []
        for item in native:
            day = _date_text(item.get("date"))
            if not day or day < start or day > end:
                continue
            rows.append({
                "date": day,
                "open": float(item["open"]), "high": float(item["high"]),
                "low": float(item["low"]), "close": float(item["close"]),
                "volume": float(item["volume"]), "amount": float(item["amount"]),
            })
        return rows, hashlib.sha256(raw).hexdigest(), final_url

    def _sse_equity_population(self, *, historical: bool, include_b_shares: bool = False) -> list[dict[str, Any]]:
        """Read the complete paginated exchange rows before applying user filters."""
        base = {
            "REG_PROVINCE": "", "CSRC_CODE": "", "STOCK_CODE": "",
            "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L", "type": "inParams",
            "isPagination": "true", "pageHelp.cacheSize": "1", "STOCK_TYPE": "1,8",
        }
        rows: list[dict[str, Any]] = []
        for status, label in (("2,4,5,7,8", "current"), ("3", "terminated")):
            if label == "terminated" and not historical:
                continue
            stock_contracts = [("1,8", "A")]
            if include_b_shares:
                stock_contracts.append(("2", "B"))
            for stock_type, share_type in stock_contracts:
                count_before_status = len(rows)
                expected_total: int | None = None
                page = 1
                while True:
                    raw, url = self._get(
                        f"sse_equity_{label}_{share_type.lower()}_population_page_{page}",
                        "https://query.sse.com.cn/sseQuery/commonQuery.do",
                        params={**base, "COMPANY_STATUS": status, "STOCK_TYPE": stock_type,
                                "pageHelp.pageSize": "1000", "pageHelp.pageNo": str(page),
                                "pageHelp.beginPage": str(page), "pageHelp.endPage": str(page)},
                        referer="https://www.sse.com.cn/assortment/stock/list/",
                    )
                    payload = json.loads(raw.decode("gbk", errors="replace"))
                    page_rows = payload.get("result")
                    help_row = payload.get("pageHelp")
                    if not isinstance(page_rows, list) or not isinstance(help_row, Mapping):
                        raise FirstInstallSourceError("SSE Equity population lacks complete pagination evidence")
                    if not isinstance(help_row.get("data"), list) or len(help_row["data"]) != len(page_rows):
                        raise FirstInstallSourceError("SSE Equity population page data disagrees with result")
                    total, count, reported = (int(help_row[key]) for key in ("total", "pageCount", "pageNo"))
                    if reported != page or total < 0 or count < 1 or count > 100 or (expected_total is not None and total != expected_total):
                        raise FirstInstallSourceError("SSE Equity population pagination changed")
                    expected_total = total
                    for row in page_rows:
                        code_value = row.get("B_STOCK_CODE") if share_type == "B" else (row.get("A_STOCK_CODE") or row.get("COMPANY_CODE"))
                        code = str(code_value or "").zfill(6)
                        if not code or code == "000000":
                            raise FirstInstallSourceError("SSE Equity population contains a missing share code")
                        display_name = _display_text(row.get("SEC_NAME_CN"), row.get("SEC_NAME_FULL"), row.get("COMPANY_ABBR"), fallback="")
                        rows.append({"venue": "SSE", "code": code,
                                     "listing_start": _date_text(row.get("LIST_DATE")),
                                     "listing_end": _date_text(row.get("DELIST_DATE")) or None,
                                     "display_name": display_name,
                                     "board": "SSE B Share" if share_type == "B" else ("SSE STAR Market" if code.startswith("688") else "SSE Main Board"),
                                     "share_type": share_type, "evidence_refs": [url], "source_row": row})
                    if page >= count:
                        if len(rows) - count_before_status != total:
                            raise FirstInstallSourceError("SSE Equity population is incomplete")
                        break
                    page += 1
        return rows

    def _szse_equity_population(self, *, historical: bool) -> list[dict[str, Any]]:
        """Read current and, when requested, terminated exchange listing episodes."""
        rows: list[dict[str, Any]] = []
        routes = [("current", "1110", "tab1", "https://www.szse.cn/market/product/stock/list/index.html")]
        if historical:
            routes.append(("terminated", "1793_ssgs", "tab2", "https://www.szse.cn/market/stock/suspend/index.html"))
        for label, catalog, tab, referer in routes:
            raw, url = self._get(
                f"szse_equity_{label}_population", "https://www.szse.cn/api/report/ShowReport",
                params={"SHOWTYPE": "xlsx", "CATALOGID": catalog, "TABKEY": tab,
                        "random": "0.3141592653589793"},
                referer=referer,
            )
            if label == "current":
                source_rows = [
                    {"code": _code_text(row["证券代码"]), "start": _date_text(row["上市日期"]),
                     "end": None, "name": str(row["证券简称"]),
                     "share_type": str(row["share_type"])}
                    for row in parse_szse_current_share_classes(raw)
                ]
            else:
                source_rows = [
                    {"code": _code_text(row["证券代码"]), "start": _date_text(row["上市日期"]),
                     "end": _date_text(row["终止上市日期"]), "name": str(row["证券简称"] or ""),
                     "share_type": mainland_share_type("SZSE", _code_text(row["证券代码"]))}
                    for row in parse_szse_terminated_workbook(raw)
                ]
            for row in source_rows:
                if not row["start"] or row["end"] is not None and not row["end"]:
                    raise FirstInstallSourceError("SZSE Equity directory lacks lifecycle dates")
                try:
                    start = date.fromisoformat(row["start"])
                    end = date.fromisoformat(row["end"]) if row["end"] else None
                except ValueError as exc:
                    raise FirstInstallSourceError("SZSE Equity directory has invalid lifecycle dates") from exc
                if end is not None and end < start:
                    raise FirstInstallSourceError("SZSE Equity directory has inverted lifecycle dates")
                rows.append({"venue": "SZSE", "code": row["code"], "listing_start": row["start"],
                             "listing_end": row["end"], "display_name": row["name"],
                             "board": "SZSE B Share" if row["share_type"] == "B" else
                                      ("SZSE ChiNext" if row["code"].startswith(("300", "301")) else "SZSE Main Board"),
                             "share_type": row["share_type"],
                             "evidence_refs": [url]})
        by_code: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_code.setdefault(row["code"], []).append(row)
        for code, episodes in by_code.items():
            ordered = sorted(episodes, key=lambda row: row["listing_start"])
            for earlier, later in zip(ordered, ordered[1:]):
                if earlier["listing_end"] is None or earlier["listing_end"] >= later["listing_start"]:
                    raise FirstInstallSourceError(f"SZSE Equity {code} has overlapping or open listing episodes")
        return rows

    def acquire(
        self, profile: DesiredDataProfile, *, run_id: str, as_of_date: str,
    ) -> dict[str, Any]:
        """Acquire the explicit denominator and its bounded requested facts."""
        profile.validate()
        contract = load_source_contract()
        if profile.source_contract_id != contract["contract_id"] or profile.source_contract_version != contract["contract_version"]:
            raise FirstInstallSourceError("Desired Data Profile uses another source contract")
        if any(scope.state == "enabled" and scope.full_available_history for scope in profile.scopes):
            raise FirstInstallSourceError(
                "source contract cannot reconstruct full available history; "
                "an as-of-date acquisition cannot satisfy this request"
            )
        if _profile_requests_hkex(profile, contract):
            _load_hkex_reference()  # Fail before any provider/source request.
        population: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        source_details: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        population_definition: dict[str, dict[str, Any]] = {}
        fund_client = PublicFundSourceClient(self.root / "fund", timeout=self.timeout, session=self.session)
        fund_sse_rows: list[dict[str, Any]] | None = None
        fund_szse_rows: list[dict[str, Any]] | None = None
        fund_szse_episodes: dict[str, dict[str, Any]] = {}

        for scope in profile.scopes:
            if scope.state != "enabled":
                continue
            scope_gap_start = len(gaps)
            supported_venues = set(contract["universes"][scope.universe]["bootstrap_executable_venues"])
            if scope.population_mode == "explicit_selection":
                selectors = list(scope.population_spec["selectors"])
                source_discovered_count = len(selectors)
                requested_codes: set[str] = set()
                discovery_limit: int | None = None
            else:
                requested_venues = set(scope.population_spec.get("venues") or supported_venues)
                if requested_venues - supported_venues:
                    raise FirstInstallSourceError(f"unsupported bootstrap venues: {sorted(requested_venues - supported_venues)}")
                requested_codes = {str(code).strip() for code in scope.population_spec.get("codes") or []}
                if requested_codes and len(requested_venues) == 1:
                    only_venue = next(iter(requested_venues))
                    requested_codes = {_code_text(code, venue=only_venue) for code in requested_codes}
                discovery_limit_raw = scope.population_spec.get("discovery_limit")
                if discovery_limit_raw is None:
                    discovery_limit = None
                else:
                    try:
                        discovery_limit = int(discovery_limit_raw)
                    except (TypeError, ValueError) as exc:
                        raise FirstInstallSourceError("discovery_limit must be a positive integer") from exc
                    if discovery_limit < 1 or discovery_limit > 100:
                        raise FirstInstallSourceError("discovery_limit must be between 1 and 100")
                discovered: list[dict[str, Any]] = []
                source_discovered_count = 0
                historical = scope.population_mode == "historical_interval_population"
                if scope.universe == "CN_PUBLIC_FUND":
                    if "SSE" in requested_venues:
                        if fund_sse_rows is None:
                            fund_sse_rows = fund_client.sse_listings()
                        source_discovered_count += sum(
                            not requested_codes or str(row.get("FUND_CODE") or "").zfill(6) in requested_codes
                            for row in fund_sse_rows
                        )
                        discovered.extend({"venue": "SSE", "code": str(row["FUND_CODE"]).zfill(6),
                                           "listing_start": _date_text(row.get("LISTING_DATE"))}
                                          for row in fund_sse_rows)
                    if "SZSE" in requested_venues:
                        if fund_szse_rows is None:
                            fund_szse_rows = fund_client.szse_listings()
                        source_discovered_count += sum(
                            not requested_codes or str(row.get("code") or "").zfill(6) in requested_codes
                            for row in fund_szse_rows
                        )
                        for row in fund_szse_rows:
                            code = str(row["code"]).zfill(6)
                            if requested_codes and code not in requested_codes:
                                continue
                            try:
                                resolution = fund_client.szse_lifecycle_for_code(code, str(row["kind"]))
                            except FundIdentityReviewRequired as exc:
                                gaps.append({"gap_type": "identity_blocked", "universe": scope.universe,
                                             "venue": "SZSE", "code": code,
                                             "population_role": "current_source_row_lifecycle_unresolved",
                                             "reason": str(exc), "promoted_fact_count": 0,
                                             "evidence_refs": []})
                                continue
                            episodes = [episode for episode in resolution["episodes"] if episode["listing_end_date"] is None]
                            if len(episodes) != 1:
                                raise FirstInstallSourceError(f"SZSE Fund {code} has no unique current listing")
                            fund_szse_episodes[code] = episodes[0]
                            discovered.append({"venue": "SZSE", "code": code,
                                               "listing_start": str(episodes[0]["listing_start_date"]),
                                               "fund_kind": row["kind"]})
                    if historical:
                        for venue in sorted(requested_venues):
                            gaps.append({"gap_type": "source_unsupported", "universe": scope.universe,
                                         "venue": venue, "code": "*", "population_role": "terminated_historical_listings_not_in_current_directory",
                                         "time_start": scope.history_start, "time_end": scope.history_end,
                                         "promoted_fact_count": 0,
                                         "evidence_refs": ["current exchange Fund directory is not a historical denominator"]})
                else:
                    if "SSE" in requested_venues:
                        discovered.extend(self._sse_equity_population(historical=historical, include_b_shares=True))
                    if "SZSE" in requested_venues:
                        discovered.extend(self._szse_equity_population(historical=historical))
                    if "BSE" in requested_venues:
                        if historical:
                            gaps.append({"gap_type": "source_unsupported", "universe": scope.universe,
                                         "venue": "BSE", "code": "*", "population_role": "bse_terminated_history_not_in_current_directory",
                                         "time_start": scope.history_start, "time_end": scope.history_end,
                                         "promoted_fact_count": 0, "evidence_refs": ["BSE current directory is not a historical denominator"]})
                        discovered.extend(self._bse_equity_population())
                    if "HKEX" in requested_venues:
                        if historical:
                            gaps.append({"gap_type": "source_unsupported", "universe": scope.universe,
                                         "venue": "HKEX", "code": "*", "population_role": "provider_current_population_not_complete_historical_denominator",
                                         "time_start": scope.history_start, "time_end": scope.history_end,
                                         "promoted_fact_count": 0, "evidence_refs": [SINA_HK_SPOT_URL, EASTMONEY_HK_SPOT_URL]})
                        hk_rows, hk_gaps, hk_denominator = self._hkex_equity_population()
                        discovered.extend(hk_rows)
                        gaps.extend(hk_gaps)
                        source_discovered_count += hk_denominator
                    source_discovered_count = sum(
                        not requested_codes or _code_text(row.get("code"), venue=str(row.get("venue"))) in requested_codes
                        for row in discovered
                    ) + sum(
                        row.get("venue") == "HKEX" and row.get("code") not in {None, "*"}
                        for row in gaps[scope_gap_start:]
                    )
                # A no-code request may intentionally bound the downstream
                # identity/fact work after the complete supported directory has
                # been read.  The package retains the full discovery count while
                # the selected rows remain source-discovered, never caller-coded.
                if discovery_limit is not None and not requested_codes:
                    discovered = discovered[:discovery_limit]
                selectors = [row for row in discovered if (not requested_codes or row["code"] in requested_codes)
                             and (not historical or (row.get("listing_start") or "") <= str(scope.history_end)
                                  and (not row.get("listing_end") or row["listing_end"] >= str(scope.history_start)))]
                if requested_codes - {row["code"] for row in selectors}:
                    gaps.extend({"gap_type": "identity_blocked", "universe": scope.universe,
                                 "code": code, "population_role": "requested_code_not_resolved_by_exchange_directory",
                                 "time_start": scope.history_start, "time_end": scope.history_end,
                                 "promoted_fact_count": 0, "evidence_refs": []}
                                for code in sorted(requested_codes - {row["code"] for row in selectors}))
            hkex_explicit_rows: list[dict[str, Any]] | None = None
            for selector in selectors:
                venue = str(selector.get("venue") or "").upper()
                code = _code_text(selector.get("code"), venue=venue)
                expected_start = str(selector.get("listing_start") or "")
                if venue not in supported_venues:
                    raise FirstInstallSourceError(f"source contract does not execute {scope.universe} venue {venue}")
                if scope.universe == "CN_PUBLIC_FUND":
                    if venue == "SSE":
                        if fund_sse_rows is None:
                            fund_sse_rows = fund_client.sse_listings()
                        listings = [row for row in fund_sse_rows if str(row.get("FUND_CODE") or "").zfill(6) == code]
                    else:
                        if fund_szse_rows is None:
                            fund_szse_rows = fund_client.szse_listings()
                        listings = [row for row in fund_szse_rows if str(row.get("code") or "").zfill(6) == code]
                    if len(listings) != 1:
                        raise FirstInstallSourceError(f"{venue} Fund code {code} is absent or ambiguous")
                    listing = listings[0]
                    if venue == "SSE":
                        actual_start = _date_text(listing.get("LISTING_DATE"))
                        listing_end = None
                        listing_name = _display_text(listing.get("FUND_EXPANSION_ABBR"), listing.get("FUND_ABBR"), fallback=code)
                        evidence = ["https://query.sse.com.cn/commonQuery.do"]
                    else:
                        episode = fund_szse_episodes.get(code)
                        if episode is None:
                            resolution = fund_client.szse_lifecycle_for_code(code, str(listing["kind"]))
                            episodes = [row for row in resolution["episodes"] if row["listing_end_date"] is None]
                            if len(episodes) != 1:
                                raise FirstInstallSourceError(f"SZSE Fund {code} has no unique current episode")
                            episode = episodes[0]
                        actual_start = str(episode["listing_start_date"])
                        listing_end = episode["listing_end_date"]
                        listing_name = _display_text(listing.get("name"), fallback=code)
                        evidence = [str(row["document_url"]) for row in episode["start_evidence"]]
                    if not actual_start or not evidence:
                        raise FirstInstallSourceError(f"{venue} Fund {code} lacks authoritative lifecycle evidence")
                    if expected_start and actual_start != expected_start:
                        raise FirstInstallSourceError("requested Fund listing episode differs from SSE evidence")
                    try:
                        detail = fund_client.resolve_csrc_product_for_code(code)
                    except FundIdentityReviewRequired as exc:
                        if scope.population_mode == "explicit_selection":
                            raise
                        gaps.append({"gap_type": "identity_blocked", "universe": scope.universe,
                                     "venue": venue, "code": code,
                                     "population_role": "current_source_row_regulator_identity_unresolved",
                                     "reason": str(exc), "promoted_fact_count": 0,
                                     "evidence_refs": evidence})
                        continue
                    evidence.insert(0, str(detail["source_url"]))
                    population.append({
                        "universe": scope.universe, "venue": venue, "code": code,
                        "listing_start": actual_start, "listing_end": listing_end,
                        "display_name": _display_text(listing_name, detail["fund_name"], fallback=code),
                        "fund_name": detail["fund_name"], "fund_product_id": str(detail["csrc_eid_fund_id"]),
                        "contract_effective_date": detail["contract_effective_date"], "evidence_refs": evidence,
                    })
                    effective_start = max(str(scope.history_start), actual_start)
                    effective_end = min(str(scope.history_end), str(listing_end)) if listing_end else str(scope.history_end)
                    valuation_rows = (fund_client.csrc_valuations(effective_start, effective_end, fund_code=code)
                                      if effective_start <= effective_end else [])
                    for item in valuation_rows:
                        if str(item.get("code") or "").zfill(6) != code:
                            continue
                        day = _date_text(item.get("valuationDate") or item.get("reportSendDate"))
                        if day < actual_start or listing_end and day > listing_end:
                            continue
                        for metric, field in (("fund.nav", "shareNetValue"), ("fund.accumulated_nav", "totalNetValue")):
                            value = item.get(field)
                            if value in (None, ""):
                                continue
                            material = {"provider": "CSRC_EID", "code": code, "date": day, "field": field, "record": item.get("idStr")}
                            observations.append({
                                "observation_key": stable_key("source_observation", material),
                                "universe": scope.universe, "venue": venue, "code": code,
                                "listing_start": actual_start, "metric_id": metric, "economic_time": day,
                                "value": float(value), "unit": "currency_per_fund_unit", "currency": "CNY",
                                "source_provider": "CSRC_EID", "binding_status": "identity_resolved",
                                "source_trace": {"source_interface": "getPublicFundJZInfoMore.do", "source_field_locator": field, "mapping_basis": "CSRC Fund ID plus scoped share-class code", "direct_url": "https://eid.csrc.gov.cn/fund/disclose/instance/getPublicFundJZInfoMore.do"},
                                "source_record": dict(item),
                            })
                else:
                    requested_share_type = (
                        "HKEX_EQUITY" if venue == "HKEX" else
                        mainland_share_type(venue, code, str(selector.get("share_type") or "") or None)
                    )
                    if venue == "HKEX" and scope.population_mode == "explicit_selection":
                        if hkex_explicit_rows is None:
                            hkex_explicit_rows, hkex_gaps, _ = self._hkex_equity_population()
                            gaps.extend(hkex_gaps)
                        matches = [row for row in hkex_explicit_rows if row["code"] == code
                                   and (not expected_start or row.get("listing_start") == expected_start)]
                        if len(matches) != 1:
                            gaps.append({"gap_type": "identity_blocked", "universe": scope.universe,
                                         "venue": "HKEX", "code": code,
                                         "population_role": "requested_hkex_code_not_accepted_by_official_reconciliation",
                                         "promoted_fact_count": 0, "evidence_refs": [HKEX_SECURITIES_URL]})
                            continue
                        selector = matches[0]
                    if "evidence_refs" in selector:
                        actual_start = selector.get("listing_start")
                        end = selector.get("listing_end")
                        listing_name = str(selector["display_name"])
                        board = str(selector["board"])
                        evidence_refs = list(selector["evidence_refs"])
                    elif venue == "SSE":
                        listing, listing_url = self._sse_equity_episode(code, expected_start or None)
                        actual_start = _date_text(listing.get("LIST_DATE"))
                        end = _date_text(listing.get("DELIST_DATE")) or None
                        listing_name = _display_text(listing.get("SEC_NAME_CN"), listing.get("COMPANY_ABBR"), listing.get("FULL_NAME"), fallback=code)
                        board = "SSE B Share" if requested_share_type == "B" else ("SSE STAR Market" if code.startswith("688") else "SSE Main Board")
                        evidence_refs = [listing_url]
                    elif venue == "SZSE":
                        candidates = [row for row in self._szse_equity_population(historical=False)
                                      if row["code"] == code and (not expected_start or row["listing_start"] == expected_start)]
                        if len(candidates) != 1:
                            raise FirstInstallSourceError(f"SZSE Equity {code} has ambiguous listing episodes")
                        chosen = candidates[0]
                        actual_start = str(chosen["listing_start"])
                        end = chosen["listing_end"]
                        listing_name = str(chosen["display_name"])
                        board = str(chosen["board"])
                        evidence_refs = list(chosen["evidence_refs"])
                    else:
                        candidates = [row for row in self._bse_equity_population() if row["code"] == code and (not expected_start or row["listing_start"] == expected_start)]
                        if len(candidates) != 1:
                            raise FirstInstallSourceError(f"BSE Equity {code} has no unique current listing")
                        chosen = candidates[0]
                        actual_start = str(chosen["listing_start"])
                        end = chosen.get("listing_end")
                        listing_name = str(chosen["display_name"])
                        board = str(chosen["board"])
                        evidence_refs = list(chosen["evidence_refs"])
                    unknown_hkex_episode = (
                        venue == "HKEX" and not actual_start
                        and selector.get("accepted_listing_id")
                        and selector.get("observation_attribution") in {
                            "unique_current_episode_in_accepted_graph",
                        }
                    )
                    if not actual_start and not unknown_hkex_episode:
                        raise FirstInstallSourceError(f"{venue} Equity listing lacks authoritative start date")
                    population.append({
                        "universe": scope.universe, "venue": venue, "code": code,
                        "listing_start": actual_start, "listing_end": end,
                        "display_name": listing_name, "board": board, "share_type": requested_share_type,
                        **({"trading_currency": selector.get("trading_currency"),
                            "daily_source_contract": selector.get("daily_source_contract")}
                           if venue == "HKEX" else {}),
                        **({"accepted_listing_id": selector.get("accepted_listing_id"),
                            "current_identity_resolution": selector.get("current_identity_resolution"),
                            "listing_start_boundary": selector.get("listing_start_boundary"),
                            "observation_attribution": selector.get("observation_attribution")}
                           if venue == "HKEX" else {}),
                        "evidence_refs": evidence_refs,
                    })
                    effective_start = max(str(scope.history_start), actual_start) if actual_start else str(scope.history_start)
                    effective_end = min(str(scope.history_end), str(end)) if end else str(scope.history_end)
                    if effective_start <= effective_end and (date.fromisoformat(effective_end) - date.fromisoformat(effective_start)).days > 640:
                        raise FirstInstallSourceError("bounded daily-source bootstrap request exceeds 640 calendar days")
                    if effective_start <= effective_end:
                        if venue == "HKEX":
                            quote_currency = str(selector.get("trading_currency") or "")
                            usd_contract = selector.get("daily_source_contract") or {}
                            if not hkex_public_provider_routes_enabled(self.provider_configuration):
                                normalized, retained_details, response_hash, daily_url = [], [], "", ""
                                gaps.append({
                                    "gap_type": "provider_unconfigured", "universe": scope.universe,
                                    "venue": venue, "code": code,
                                    "population_role": "official_identity_retained_daily_provider_unconfigured",
                                    "time_start": effective_start, "time_end": effective_end,
                                    "promoted_fact_count": 0, "evidence_refs": evidence_refs,
                                })
                            elif quote_currency != "HKD" and (
                                quote_currency != "USD" or usd_contract.get("quote_currency") != "USD"
                                or usd_contract.get("source") != "Sina hkstock_klc2_kl.js"
                            ):
                                normalized, retained_details, response_hash, daily_url = [], [], "", ""
                                gaps.append({
                                    "gap_type": "source_unsupported", "universe": scope.universe,
                                    "venue": venue, "code": code,
                                    "population_role": "hkex_non_hkd_daily_source_contract_not_proved_identity_retained",
                                    "time_start": effective_start, "time_end": effective_end,
                                    "promoted_fact_count": 0, "evidence_refs": evidence_refs,
                                })
                            else:
                                native, response_hash, daily_url = self._hkex_equity_daily(code, effective_start, effective_end)
                                supported_from = "0000-01-01" if quote_currency == "HKD" else usd_contract.get("sina_ohlcv_supported_from")
                                promote_amount = quote_currency == "HKD" or usd_contract.get("promote_amount") is True
                                normalized = sina_hk_daily_observations(
                                    native, code=code, listing_id="source_stage_only", response_sha256=response_hash,
                                    quote_currency=quote_currency, supported_from=supported_from,
                                    promote_amount=promote_amount,
                                )
                                retained_details = sina_hk_daily_source_details(
                                    native, code=code, listing_id="source_stage_only", response_sha256=response_hash,
                                    supported_from=supported_from, promote_amount=promote_amount,
                                )
                                if quote_currency != "HKD":
                                    if supported_from is None or effective_start < supported_from:
                                        gaps.append({
                                            "gap_type": "source_unsupported", "universe": scope.universe,
                                            "venue": venue, "code": code, "population_role": "hkex_usd_price_regime_unproved_or_unusable",
                                            "time_start": effective_start,
                                            "time_end": min(effective_end, supported_from) if supported_from else effective_end,
                                            "promoted_fact_count": 0, "evidence_refs": evidence_refs,
                                        })
                                    if not promote_amount:
                                        gaps.append({
                                            "gap_type": "source_unsupported", "universe": scope.universe,
                                            "venue": venue, "code": code, "metric_id": "market.trade_amount",
                                            "population_role": "hkex_usd_native_amount_scale_unproved",
                                            "time_start": effective_start, "time_end": effective_end,
                                            "promoted_fact_count": 0, "evidence_refs": evidence_refs,
                                        })
                        else:
                            native, response_hash, daily_url = self._sse_equity_daily(code, effective_start, effective_end, venue=venue)
                            normalized = daily_observations(
                                native, exchange=venue, code=code, listing_id="source_stage_only",
                                source_response_hash=response_hash, share_type=requested_share_type,
                            )
                            retained_details = daily_source_details(
                                native, exchange=venue, code=code, listing_id="source_stage_only",
                                source_response_hash=response_hash, share_type=requested_share_type,
                            )
                    else:
                        normalized, retained_details, response_hash, daily_url = [], [], "", ""
                    for item in normalized:
                        day = str(item["economic_time"])
                        if (scope.history_start and day < scope.history_start or scope.history_end and day > scope.history_end
                                or actual_start and day < actual_start or end and day > end):
                            continue
                        observations.append({
                            "observation_key": item["source_observation_key"], "universe": scope.universe,
                            "venue": venue, "code": code, "listing_start": actual_start,
                            "metric_id": item["metric_id"], "economic_time": day,
                            "value": float(item["normalized_value"]), "unit": item["canonical_unit"],
                            "currency": item["canonical_currency"], "source_provider": "Sina" if venue == "HKEX" else "Tencent",
                            "binding_status": "identity_resolved",
                            "source_trace": {"source_interface": item["source_interface"], "source_field_locator": item["raw_field"], "adjustment_basis": "unadjusted", "mapping_basis": f"{venue} lifecycle episode plus effective code alias", "direct_url": daily_url, "response_sha256": response_hash},
                            "source_record": dict(item),
                        })
                    for detail in retained_details:
                        day = str(detail["economic_time"])
                        if (scope.history_start and day < scope.history_start or scope.history_end and day > scope.history_end
                                or actual_start and day < actual_start or end and day > end):
                            continue
                        source_details.append({
                            **detail,
                            "universe": scope.universe,
                            "venue": venue,
                            "code": code,
                            "listing_start": actual_start,
                            "binding_status": "identity_resolved",
                            "source_trace": {
                                "source_interface": detail["source_interface"],
                                "source_field_locator": detail["source_field"],
                                "adjustment_basis": "unadjusted",
                                "mapping_basis": f"{venue} accepted lifecycle episode plus effective code alias; source field not promoted",
                                "direct_url": daily_url,
                                "response_sha256": response_hash,
                            },
                            "source_record": dict(detail),
                        })
                    if requested_share_type == "B" and retained_details:
                        gaps.append({
                            "gap_type": "source_unsupported", "universe": scope.universe,
                            "venue": venue, "code": code, "metric_id": "market.trade_amount",
                            "time_start": effective_start, "time_end": effective_end,
                            "reason": "Tencent field8 native amount currency/scale is not proved for this B-share venue/time regime",
                            "promoted_fact_count": 0, "source_detail_count": len(retained_details),
                            "evidence_refs": [daily_url],
                        })
                selected = [row for row in observations if row["universe"] == scope.universe and row["venue"] == venue and row["code"] == code and row["listing_start"] == actual_start]
                dates = sorted({row["economic_time"] for row in selected})
                if effective_start <= effective_end:
                    if not dates:
                        gaps.append({"gap_type": "source_unavailable", "universe": scope.universe, "venue": venue, "code": code, "time_start": effective_start, "time_end": effective_end, "promoted_fact_count": 0, "evidence_refs": [receipt["url"] for receipt in self.receipts[-2:]]})
                    else:
                        if dates[0] > effective_start:
                            gaps.append({"gap_type": "source_unavailable", "universe": scope.universe, "venue": venue, "code": code, "time_start": effective_start, "time_end": dates[0], "promoted_fact_count": 0, "evidence_refs": ["bounded public-source response"]})
                        if dates[-1] < effective_end:
                            gaps.append({"gap_type": "source_unavailable", "universe": scope.universe, "venue": venue, "code": code, "time_start": dates[-1], "time_end": effective_end, "promoted_fact_count": 0, "evidence_refs": ["bounded public-source response"]})

            population_definition[scope.universe] = {
                "population_mode": scope.population_mode,
                "requested_venues": sorted({str(row.get("venue") or "").upper() for row in selectors})
                if scope.population_mode == "explicit_selection" else sorted(requested_venues),
                "requested_codes": sorted(requested_codes) if scope.population_mode != "explicit_selection" else
                sorted({_code_text(row.get("code"), venue=str(row.get("venue"))) for row in selectors}),
                "discovery_limit": discovery_limit,
                "requested_interval": {"start": scope.history_start, "end": scope.history_end,
                                       "full_available_history": scope.full_available_history},
                "source_discovered_episode_count": source_discovered_count,
                "discovered_episode_count": sum(row["universe"] == scope.universe for row in population),
                "gap_count": len(gaps) - scope_gap_start,
                "source_receipt_count": len(self.receipts) + len(fund_client.calls),
            }

        self.receipts.extend(fund_client.calls)
        result = {
            "schema_version": SOURCE_PACKAGE_SCHEMA, "source_contract_id": profile.source_contract_id,
            "source_contract_version": profile.source_contract_version, "run_id": run_id,
            "as_of_date": as_of_date, "population": population,
            "population_definition": population_definition,
            "observations": observations, "source_details": source_details, "gaps": gaps,
            "acquisition_receipts": self.receipts,
            "developer_legacy_inputs_read": 0,
        }
        write_json_atomic(self.root / "normalized_source_package_v1.json", result)
        write_json_atomic(self.root / "source_acquisition_receipts_v1.json", {"schema_version": "fr_first_install_source_receipts_v1", "receipts": self.receipts})
        return result
