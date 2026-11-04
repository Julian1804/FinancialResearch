from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.parse
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import requests
from pypdf import PdfReader

from backend.app.core.china_equity_source_semantics import (
    ACCEPTED_A_SHARE_FINANCIAL_METRICS,
    DAILY_METRIC_CONTRACT,
    daily_observations,
    daily_source_details,
    daily_metric_contract,
    ensure_discovered_listing_identity,
    discovered_listing_identity_decisions,
    financial_statement_observations,
    mainland_share_type,
    parse_bse_current_pages,
    parse_cninfo_subject_crosswalk,
    parse_sina_financial_response,
    parse_sse_current_payloads,
    parse_szse_current_share_classes,
    parse_tencent_daily_response,
)
from backend.app.core.china_equity_foundation import AcceptedChinaEquityEpisodeIndex
from backend.app.core.china_equity_bounded_plan import BoundedPlanPayloadWriter, bounded_payload_count
from backend.app.core.artifact_io import canonical_json, sha256_file, stable_key, write_json_atomic
from backend.app.core.source_transport import sha256_bytes
from backend.app.core.china_equity_identifiers import normalize_listing_code
from backend.app.core.hkex_equity_sources import (
    EASTMONEY_HK_SPOT_URL,
    HKEX_SECURITIES_URL,
    SINA_HK_SPOT_URL,
    current_economic_population_from_reference,
    decode_sina_hk_daily_payload,
    parse_hkex_securities_workbook,
    parse_eastmoney_hk_spot_payload,
    parse_sina_hk_spot_payload,
    reconcile_hkex_provider_candidates,
    hkex_public_provider_routes_enabled,
    installation_provider_route_enabled,
    load_provider_route_configuration,
    sina_hk_daily_observations,
    sina_hk_daily_source_details,
)
from backend.app.core.hong_kong_equity_ownership import (
    accepted_hkex_change_or_none,
    allocate_accepted_hkex_changes,
    episode_key_for_change,
)
from backend.app.core.storage_profile import resolve_temporary_workspace_path, resolve_unpublished_control_path, resolve_unpublished_snapshot_path


SOURCE_FAMILY_PROCESSING_CONTRACTS = {
    "documents": "fr_document_asset_v1",
    "financial": "a_share_financial_applicable_scope_v2",
    "reality": "a_share_lifecycle_evidence_v3",
}
HKEX_REFERENCE_PATH = Path(__file__).resolve().parents[3] / "config" / "fr_hkex_equity_population_reference_v1.json"


class AcceptedSourceTransportError(RuntimeError):
    """The configured public source could not provide a complete response."""


class MarketCheckIncomplete(RuntimeError):
    """A required route for one market did not complete; no head may advance."""

    def __init__(self, market_scope: str, reasons: list[str]):
        self.market_scope = market_scope
        self.reasons = tuple(reasons)
        super().__init__(f"{market_scope} required check incomplete: {', '.join(reasons)}")


def _hkex_provider_configured(config: "UserUpdateConfig") -> bool:
    """Use the same installation-local route decision for discovery and daily acquisition."""
    return config.source_mode != "live" or hkex_public_provider_routes_enabled(load_provider_route_configuration())


def resolve_equity_predecessor_control_dependency(snapshot_id: str) -> dict[str, Any]:
    """Resolve a control DB owned by this head or proved inherited by it.

    The accepted manifest-only Equity head changed no business member. Its
    direct predecessor's control is consequently the exact logical control
    input, but only after checking the immutable file inventories and the
    zero-business-delta reconciliation state. Never search older seed controls.
    """
    direct = resolve_unpublished_control_path(snapshot_id)
    if direct.is_file():
        return {"path": str(direct), "owner_snapshot_id": snapshot_id, "binding": "direct"}
    root = resolve_unpublished_snapshot_path(snapshot_id)
    state = json.loads((root / "metadata/a_share_update/validated_update_state_v1.json").read_text(encoding="utf-8"))
    reconciliation = state.get("metadata_reconciliation") or {}
    if reconciliation.get("kind") != "manifest_aggregate_reconciliation" or reconciliation.get("business_delta_count") != 0:
        raise FileNotFoundError(f"Equity head has no proved inherited control: {snapshot_id}")
    predecessor_id = str(state.get("predecessor_snapshot_id") or "")
    if not predecessor_id or predecessor_id == snapshot_id:
        raise ValueError("Equity manifest reconciliation has no unique direct predecessor")
    predecessor_control = resolve_unpublished_control_path(predecessor_id)
    if not predecessor_control.is_file():
        raise FileNotFoundError(f"Equity direct predecessor control is unavailable: {predecessor_id}")
    current_manifest = json.loads((root / "metadata/corrected_candidate_manifest_v1.json").read_text(encoding="utf-8"))
    previous_manifest = json.loads((resolve_unpublished_snapshot_path(predecessor_id) / "metadata/corrected_candidate_manifest_v1.json").read_text(encoding="utf-8"))
    if (current_manifest.get("snapshot_id") != snapshot_id
            or current_manifest.get("predecessor_snapshot_id") != predecessor_id
            or previous_manifest.get("snapshot_id") != predecessor_id):
        raise ValueError("Equity manifest reconciliation predecessor identity mismatch")

    def members(manifest: Mapping[str, Any]) -> dict[str, tuple[Any, Any, Any]]:
        rows = [*manifest.get("files", []), *manifest.get("auxiliary_files", [])]
        result = {
            str(row["relative_path"]): (row.get("row_count"), row.get("byte_count"), row.get("content_sha256"))
            for row in rows
        }
        if len(result) != len(rows):
            raise ValueError("Equity manifest has duplicate member paths")
        return result

    current_members, previous_members = members(current_manifest), members(previous_manifest)
    state_member = "metadata/a_share_update/validated_update_state_v1.json"
    if (set(current_members) != set(previous_members)
            or {path: value for path, value in current_members.items() if path != state_member}
            != {path: value for path, value in previous_members.items() if path != state_member}
            or state_member not in current_members):
        raise ValueError("Equity manifest reconciliation changed a control-relevant member")
    if sha256_file(root / state_member) != current_members[state_member][2]:
        raise ValueError("Equity reconciled state does not match its accepted manifest")
    return {
        "path": str(predecessor_control),
        "owner_snapshot_id": predecessor_id,
        "binding": "proved_manifest_only_direct_predecessor",
        "effective_snapshot_id": snapshot_id,
    }


@dataclass(frozen=True)
class CurrentListingRecord:
    exchange: str
    code: str
    listing_date: str | None
    security_name: str
    source_id: str
    source_record: Mapping[str, Any]
    share_type: str = "A"


@dataclass(frozen=True)
class UserUpdateConfig:
    project_root: Path
    output_root: Path
    lifecycle_path: Path
    identity_reconciliation_path: Path
    predecessor_snapshot_id: str
    baseline_reality_date: str
    as_of_date: str
    source_mode: str = "live"
    authoritative_replay_root: Path | None = None
    provider_replay_root: Path | None = None
    source_event_replay_root: Path | None = None
    previous_update_state: Mapping[str, Any] | None = None
    source_event_overlap_days: int = 7
    selected_data_families: tuple[str, ...] | None = None
    # None preserves the historical combined execution.  A scoped run checks
    # only one independently owned market and may inherit the other market.
    market_scope: str | None = None


MARKET_SCOPE_EXCHANGES = {
    "mainland_china": frozenset({"SSE", "SZSE", "BSE"}),
    "hong_kong": frozenset({"HKEX"}),
}


def _selected_exchanges(config: UserUpdateConfig) -> frozenset[str]:
    if config.market_scope is None:
        return frozenset({"SSE", "SZSE", "BSE", "HKEX"})
    try:
        return MARKET_SCOPE_EXCHANGES[config.market_scope]
    except KeyError as exc:
        raise ValueError(f"unsupported Equity market scope: {config.market_scope}") from exc


def _as_date(value: Any) -> str:
    if hasattr(value, "date"):
        value = value.date()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    text = str(value or "").strip().replace("/", "-")
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def _request(
    session: requests.Session,
    *,
    source_id: str,
    url: str,
    target: Path,
    method: str = "GET",
    params: Mapping[str, Any] | None = None,
    data: Mapping[str, Any] | None = None,
    referer: str | None = None,
) -> dict[str, Any]:
    headers = {"User-Agent": "FinancialResearch/1.0 user-triggered A-share update"}
    if referer:
        headers["Referer"] = referer
    transport = "requests"
    try:
        response = session.request(method, url, params=params, data=data, headers=headers, timeout=60)
        response.raise_for_status()
        content = response.content
        response_url = response.url
        status = response.status_code
    except requests.exceptions.RequestException:
        szse_export = (source_id == "szse_current_a_share" and method == "GET"
                       and url == "https://www.szse.cn/api/report/ShowReport")
        hkex_eastmoney_inventory = (source_id.startswith("hkex_eastmoney_current_page_")
                                    and method == "GET" and url == EASTMONEY_HK_SPOT_URL)
        if not (szse_export or hkex_eastmoney_inventory):
            raise
        # Use only the exact accepted upstream and request parameters. Windows
        # proxy/OpenSSL can disconnect Python while curl HTTP/1.1 succeeds.
        response_url = url + "?" + urllib.parse.urlencode(params or {})
        last_error = ""
        for attempt in range(1, 4):
            curl_command = ["curl.exe", "--http1.1", "--silent", "--show-error", "--fail-with-body",
                            "--location", "--max-time", "60", "--header", f"User-Agent: {headers['User-Agent']}"]
            if referer:
                curl_command.extend(["--header", f"Referer: {referer}"])
            curl_command.append(response_url)
            completed = subprocess.run(
                curl_command,
                capture_output=True, check=False, timeout=70,
            )
            valid_payload = completed.stdout.startswith(b"PK\x03\x04") if szse_export else False
            if hkex_eastmoney_inventory and completed.returncode == 0:
                try:
                    valid_payload = isinstance(json.loads(completed.stdout), Mapping)
                except (ValueError, UnicodeError):
                    valid_payload = False
            if completed.returncode == 0 and valid_payload:
                content = completed.stdout
                status = 200
                transport = "curl_http1_fallback"
                break
            last_error = completed.stderr.decode("utf-8", errors="replace").strip() or f"curl exit {completed.returncode} or invalid source envelope"
            if attempt < 3:
                time.sleep(1.5 * attempt)
        else:
            raise AcceptedSourceTransportError(
                f"{source_id} accepted upstream transport failed after bounded retries: {last_error}"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return {
        "source_id": source_id,
        "mode": "network",
        "url": response_url,
        "http_status": status,
        "transport": transport,
        "bytes": len(content),
        "sha256": sha256_bytes(content),
        "path": str(target),
    }


def _copy_replay(source: Path, target: Path, source_id: str) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {
        "source_id": source_id,
        "mode": "retained_authoritative_replay",
        "url": None,
        "http_status": None,
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "path": str(target),
        "retained_source_path": str(source),
    }


def _copy_same_day_live_observation(source: Path, target: Path, source_id: str) -> dict[str, Any]:
    """Continue a failed live observation without claiming a new network request."""
    receipt = _copy_replay(source, target, source_id)
    receipt["mode"] = "retained_same_day_live_observation"
    receipt["origin_run_id"] = source.parent.parent.name
    return receipt


def refresh_authoritative_state(config: UserUpdateConfig) -> tuple[list[CurrentListingRecord], dict[str, Any], Path]:
    raw = config.output_root / "raw_authoritative"
    raw.mkdir(parents=True, exist_ok=True)
    selected_exchanges = _selected_exchanges(config)
    mainland_selected = bool(selected_exchanges & {"SSE", "SZSE", "BSE"})
    hong_kong_selected = "HKEX" in selected_exchanges
    receipts: list[dict[str, Any]] = []
    session = requests.Session()
    stamp = config.as_of_date.replace("-", "")
    hkex_target: Path | None = None
    hkex_sina_targets: list[Path] = []
    hkex_eastmoney_targets: list[Path] = []
    hkex_sina_complete = False
    hkex_eastmoney_complete = False
    hkex_eastmoney_failure: dict[str, Any] | None = None
    hkex_provider_configured = hong_kong_selected and _hkex_provider_configured(config)
    sse_sources: list[Path] = []
    bse_targets: list[Path] = []
    szse_target: Path | None = None
    # HK-only execution has no CNINFO issuer decision to make.  The neutral
    # empty input satisfies the existing plan parser without claiming a
    # successful CNINFO source observation.
    crosswalk_target = raw / "not_applicable_mainland_crosswalk.json"
    if not mainland_selected:
        crosswalk_target.write_text('{"stockList":[]}', encoding="utf-8")

    if config.source_mode == "replay":
        if config.authoritative_replay_root is None:
            raise ValueError("replay mode requires authoritative_replay_root")
        root = config.authoritative_replay_root
        for label in (("main", "star", "b") if mainland_selected else ()):
            source = next(iter(sorted(root.glob(f"sse_current_{label}_*.json"))), None)
            if source is None:
                if label == "b":
                    continue
                raise FileNotFoundError(f"retained SSE {label} current snapshot missing")
            target = raw / f"sse_current_{label}_{stamp}.json"
            receipts.append(_copy_replay(source, target, f"sse_current_{label}"))
            sse_sources.append(target)
        szse_source = next(iter(sorted(root.glob("szse_current_a_share_*.xlsx"))), None) if mainland_selected else None
        if mainland_selected and szse_source is None:
            raise FileNotFoundError("retained SZSE current snapshot missing")
        if szse_source is not None:
            szse_target = raw / f"szse_current_a_share_{stamp}.xlsx"
            receipts.append(_copy_replay(szse_source, szse_target, "szse_current_a_share"))
        bse_sources = sorted(root.glob("bse_current_page_*.jsonp")) if mainland_selected else []
        if mainland_selected and not bse_sources:
            raise FileNotFoundError("retained BSE current pages missing")
        for position, source in enumerate(bse_sources):
            target = raw / f"bse_current_page_{position:02d}_{stamp}.jsonp"
            receipts.append(_copy_replay(source, target, f"bse_current_page_{position:02d}"))
            bse_targets.append(target)
        hkex_source = next(iter(sorted(root.glob("hkex_current_equity_*.xlsx"))), None) if hong_kong_selected else None
        if hkex_source is not None:
            hkex_target = raw / f"hkex_current_equity_{stamp}.xlsx"
            receipts.append(_copy_replay(hkex_source, hkex_target, "hkex_current_equity"))
            for page in range(1, 100):
                source = next(iter(sorted(root.glob(f"hkex_sina_current_page_{page:03d}_*.json"))), None)
                if source is None:
                    break
                target = raw / f"hkex_sina_current_page_{page:03d}_{stamp}.json"
                receipts.append(_copy_replay(source, target, f"hkex_sina_current_page_{page:03d}"))
                hkex_sina_targets.append(target)
                if len(parse_sina_hk_spot_payload(target.read_bytes())) < 60:
                    hkex_sina_complete = True
                    break
            for page in range(1, 100):
                source = next(iter(sorted(root.glob(f"hkex_eastmoney_current_page_{page:03d}_*.json"))), None)
                if source is None:
                    break
                target = raw / f"hkex_eastmoney_current_page_{page:03d}_{stamp}.json"
                receipts.append(_copy_replay(source, target, f"hkex_eastmoney_current_page_{page:03d}"))
                hkex_eastmoney_targets.append(target)
                if len(parse_eastmoney_hk_spot_payload(target.read_bytes())) < 100:
                    hkex_eastmoney_complete = True
                    break
            if not hkex_eastmoney_complete:
                hkex_eastmoney_failure = {
                    "source_id": "hkex_eastmoney_candidate_inventory",
                    "upstream": "Eastmoney", "outcome": "not_complete_in_retained_replay",
                    "completed_page_count": len(hkex_eastmoney_targets),
                }
        crosswalk_source = next(iter(sorted(root.glob("cninfo_all_stock_subject_crosswalk_*.json"))), None) if mainland_selected else None
        if mainland_selected and crosswalk_source is None:
            raise FileNotFoundError("retained CNINFO subject crosswalk missing")
        if crosswalk_source is not None:
            crosswalk_target = raw / f"cninfo_all_stock_subject_crosswalk_{stamp}.json"
            receipts.append(_copy_replay(crosswalk_source, crosswalk_target, "cninfo_all_stock_subject_crosswalk"))
    elif config.source_mode == "live":
        base = {
            "REG_PROVINCE": "", "CSRC_CODE": "", "STOCK_CODE": "",
            "sqlId": "COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L", "COMPANY_STATUS": "2,4,5,7,8",
            "type": "inParams", "isPagination": "true", "pageHelp.cacheSize": "1",
            "pageHelp.beginPage": "1", "pageHelp.pageSize": "10000", "pageHelp.pageNo": "1", "pageHelp.endPage": "1",
        }
        for stock_type, label in ((("1", "main"), ("8", "star"), ("2", "b")) if mainland_selected else ()):
            target = raw / f"sse_current_{label}_{stamp}.json"
            receipts.append(_request(session, source_id=f"sse_current_{label}", url="https://query.sse.com.cn/sseQuery/commonQuery.do", target=target, params={**base, "STOCK_TYPE": stock_type}, referer="https://www.sse.com.cn/assortment/stock/list/share/"))
            sse_sources.append(target)
        if mainland_selected:
            szse_target = raw / f"szse_current_a_share_{stamp}.xlsx"
            receipts.append(_request(session, source_id="szse_current_a_share", url="https://www.szse.cn/api/report/ShowReport", target=szse_target, params={"SHOWTYPE": "xlsx", "CATALOGID": "1110", "TABKEY": "tab1", "random": "0.3141592653589793"}, referer="https://www.szse.cn/market/product/stock/list/index.html"))
        seen_codes: set[str] = set()
        for page in (range(100) if mainland_selected else ()):
            target = raw / f"bse_current_page_{page:02d}_{stamp}.jsonp"
            receipt = _request(session, source_id=f"bse_current_page_{page:02d}", url="https://www.bse.cn/nqxxController/nqxxCnzq.do", target=target, method="POST", data={"page": str(page), "typejb": "T", "xxfcbj[]": "2", "xxzqdm": "", "sortfield": "xxzqdm", "sorttype": "asc"}, referer="https://www.bse.cn/nq/listedcompany.html")
            receipts.append(receipt)
            page_rows = parse_bse_current_pages([target.read_text(encoding="utf-8")])
            codes = {str(row.get("xxzqdm") or "").zfill(6) for row in page_rows}
            if not codes or codes.issubset(seen_codes):
                target.unlink(missing_ok=True)
                receipts.pop()
                break
            seen_codes.update(codes)
            bse_targets.append(target)
        if mainland_selected:
            crosswalk_target = raw / f"cninfo_all_stock_subject_crosswalk_{stamp}.json"
            receipts.append(_request(session, source_id="cninfo_all_stock_subject_crosswalk", url="https://www.cninfo.com.cn/new/data/szse_stock.json", target=crosswalk_target, referer="https://www.cninfo.com.cn/"))
        hkex_continuation = config.authoritative_replay_root if hong_kong_selected else None
        if hkex_continuation is not None:
            if hkex_continuation.name != "raw_authoritative" or not hkex_continuation.is_dir():
                raise ValueError("live HKEX continuation requires a retained raw_authoritative directory")
            hkex_source = hkex_continuation / f"hkex_current_equity_{stamp}.xlsx"
            if not hkex_source.is_file():
                raise FileNotFoundError("same-day retained HKEX official directory is missing")
            hkex_target = raw / hkex_source.name
            receipts.append(_copy_same_day_live_observation(hkex_source, hkex_target, "hkex_current_equity"))
            if not hkex_provider_configured:
                raise ValueError("retained HKEX candidate observation cannot bypass provider-route configuration")
            for page in range(1, 100):
                source = hkex_continuation / f"hkex_sina_current_page_{page:03d}_{stamp}.json"
                if not source.is_file():
                    raise FileNotFoundError(f"same-day retained Sina candidate page {page} is missing")
                target = raw / source.name
                receipts.append(_copy_same_day_live_observation(source, target, f"hkex_sina_current_page_{page:03d}"))
                hkex_sina_targets.append(target)
                if len(parse_sina_hk_spot_payload(target.read_bytes())) < 60:
                    hkex_sina_complete = True
                    break
            if not hkex_sina_complete:
                raise ValueError("retained Sina candidate inventory has no terminal page")
            if (hkex_continuation / f"hkex_sina_current_page_{page + 1:03d}_{stamp}.json").exists():
                raise ValueError("retained Sina candidate inventory has pages after the terminal page")
            failure_path = hkex_continuation.parent / "chain_run_failure_v1.json"
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            completed_eastmoney = sorted(hkex_continuation.glob(f"hkex_eastmoney_current_page_*_{stamp}.json"))
            failed_page = len(completed_eastmoney) + 1
            expected_pages = [
                f"hkex_eastmoney_current_page_{page:03d}_{stamp}.json"
                for page in range(1, failed_page)
            ]
            if [path.name for path in completed_eastmoney] != expected_pages:
                raise ValueError("retained Eastmoney partial pages are not contiguous")
            if (failure.get("run_id") != hkex_continuation.parent.name
                    or failure.get("predecessor_snapshot_id") != config.predecessor_snapshot_id
                    or not str(failure.get("error") or "").startswith(
                        f"hkex_eastmoney_current_page_{failed_page:03d} ")):
                raise ValueError("retained Eastmoney source failure is not bound to this live continuation")
            hkex_eastmoney_failure = {
                "source_id": f"hkex_eastmoney_current_page_{failed_page:03d}",
                "upstream": "Eastmoney", "outcome": "incomplete_transport_failure",
                "failed_page": failed_page, "completed_page_count": len(completed_eastmoney),
                "origin_run_id": failure["run_id"], "error": failure["error"],
                "partial_candidate_count_not_promoted": sum(
                    len(parse_eastmoney_hk_spot_payload(path.read_bytes()))
                    for path in completed_eastmoney
                ),
            }
            receipts.append({"mode": "retained_source_failure", **hkex_eastmoney_failure})
        elif hong_kong_selected:
            hkex_target = raw / f"hkex_current_equity_{stamp}.xlsx"
            receipts.append(_request(session, source_id="hkex_current_equity", url=HKEX_SECURITIES_URL,
                                     target=hkex_target, referer="https://www.hkex.com.hk/"))
        if hkex_provider_configured and hkex_continuation is None:
            for page in range(1, 100):
                target = raw / f"hkex_sina_current_page_{page:03d}_{stamp}.json"
                receipts.append(_request(
                    session, source_id=f"hkex_sina_current_page_{page:03d}", url=SINA_HK_SPOT_URL,
                    target=target,
                    params={"page": str(page), "num": "60", "sort": "symbol", "asc": "1", "node": "qbgg_hk", "_s_r_a": "init"},
                ))
                hkex_sina_targets.append(target)
                if len(parse_sina_hk_spot_payload(target.read_bytes())) < 60:
                    hkex_sina_complete = True
                    break
            if not hkex_sina_complete:
                raise ValueError("Sina HKEX current-candidate pagination has no terminal page")
            for page in range(1, 100):
                target = raw / f"hkex_eastmoney_current_page_{page:03d}_{stamp}.json"
                try:
                    receipts.append(_request(
                        session, source_id=f"hkex_eastmoney_current_page_{page:03d}", url=EASTMONEY_HK_SPOT_URL,
                        target=target,
                        params={
                            "pn": str(page), "pz": "100", "po": "0", "np": "1",
                            "ut": "fa5fd1943c7b386f172d6893dbfba10b", "fltt": "2", "invt": "2",
                            "fs": "m:116+t:3,m:116+t:4", "fields": "f12,f13,f14",
                        },
                    ))
                except AcceptedSourceTransportError as exc:
                    hkex_eastmoney_failure = {
                        "source_id": f"hkex_eastmoney_current_page_{page:03d}",
                        "upstream": "Eastmoney", "outcome": "incomplete_transport_failure",
                        "failed_page": page, "completed_page_count": len(hkex_eastmoney_targets),
                        "error_type": type(exc).__name__, "error": str(exc),
                    }
                    receipts.append({"mode": "source_attempt", **hkex_eastmoney_failure})
                    break
                hkex_eastmoney_targets.append(target)
                if len(parse_eastmoney_hk_spot_payload(target.read_bytes())) < 100:
                    hkex_eastmoney_complete = True
                    break
            if not hkex_eastmoney_complete and hkex_eastmoney_failure is None:
                raise ValueError("Eastmoney HKEX current-candidate pagination has no terminal page")
            if not hkex_sina_targets:
                raise ValueError("Sina HKEX current-candidate inventory returned no pages")
    else:
        raise ValueError(f"unsupported source_mode: {config.source_mode}")

    rows: list[CurrentListingRecord] = []
    for source in sse_sources:
        for row in parse_sse_current_payloads([source.read_text(encoding="utf-8")]):
            raw_code = row.get("B_STOCK_CODE") if source.stem.startswith("sse_current_b_") else row.get("A_STOCK_CODE")
            code = str(raw_code or "").zfill(6)
            if code == "689009":
                continue
            share_type = "B" if source.stem.startswith("sse_current_b_") else "A"
            rows.append(CurrentListingRecord("SSE", code, _as_date(row.get("LIST_DATE")), str(row.get("SEC_NAME_CN") or row.get("COMPANY_ABBR") or ""), source.stem, row, share_type))
    for row in parse_szse_current_share_classes(szse_target.read_bytes()) if szse_target is not None else ():
        rows.append(CurrentListingRecord("SZSE", str(row["证券代码"]).zfill(6), _as_date(row["上市日期"]), str(row["证券简称"]), "szse_current_equity", row, str(row["share_type"])))
    for row in parse_bse_current_pages(path.read_text(encoding="utf-8") for path in bse_targets):
        rows.append(CurrentListingRecord("BSE", str(row.get("xxzqdm") or "").zfill(6), _as_date(row.get("fxssrq") or row.get("xxgprq")), str(row.get("xxzqjc") or ""), "bse_current_pages", row, "A"))
    hkex_residuals: list[dict[str, Any]] = []
    if config.market_scope == "hong_kong" and hkex_target is None:
        raise FileNotFoundError("required HKEX official current directory is missing")
    if hkex_target is not None:
        # Retained replay evidence may still use the accepted internal graph;
        # normal live Update Data never reaches this branch.
        reference = json.loads(HKEX_REFERENCE_PATH.read_text(encoding="utf-8"))
        if reference.get("schema_version") != "fr_hkex_equity_population_reference_v1":
            raise ValueError("HKEX population reference schema is unsupported")
        _updated_at, current_hkex = parse_hkex_securities_workbook(hkex_target.read_bytes())
        if config.source_mode == "live" and config.authoritative_replay_root is not None:
            try:
                workbook_date = datetime.strptime(_updated_at, "%d/%m/%Y").date().isoformat()
            except (TypeError, ValueError) as exc:
                raise ValueError("retained HKEX official directory has no verifiable update date") from exc
            if workbook_date != config.as_of_date:
                raise ValueError("retained HKEX official directory is not a same-day live observation")
        accepted_hkex, hkex_residuals = current_economic_population_from_reference(current_hkex, reference["rows"])
        for row in accepted_hkex:
            accepted = dict(row["accepted_reference"])
            rows.append(CurrentListingRecord(
                "HKEX", normalize_listing_code("HKEX", row["code"]),
                accepted.get("listing_start"), str(row["display_name"]),
                "hkex_current_equity", {**dict(row), "accepted_reference": accepted}, "HKEX_EQUITY",
            ))
    hkex_source_route_warnings: list[dict[str, Any]] = []
    if hkex_sina_targets:
        sina_rows = [item for path in hkex_sina_targets for item in parse_sina_hk_spot_payload(path.read_bytes())]
        if len({item["code"] for item in sina_rows}) != len(sina_rows):
            raise ValueError("Sina HKEX pagination contains repeated candidate codes")
        official_codes = {row.code for row in rows if row.exchange == "HKEX"}
        if hkex_eastmoney_complete:
            eastmoney_rows = [item for path in hkex_eastmoney_targets for item in parse_eastmoney_hk_spot_payload(path.read_bytes())]
            if len({item["code"] for item in eastmoney_rows}) != len(eastmoney_rows):
                raise ValueError("Eastmoney HKEX pagination contains repeated candidate codes")
            provider_rows, provider_residuals = reconcile_hkex_provider_candidates(sina_rows, eastmoney_rows)
            hkex_residuals.extend({"code": candidate["code"],
                                   "reason": "provider_candidate_without_official_directory_identity",
                                   "provider_evidence_refs": candidate.get("provider_evidence_refs")}
                                  for candidate in provider_rows if candidate["code"] not in official_codes)
            hkex_residuals.extend(provider_residuals)
        else:
            if hkex_target is None or not hkex_sina_complete or hkex_eastmoney_failure is None:
                raise ValueError("HKEX candidate fallback lacks complete official/Sina observation")
            # The official directory owns current economic population. Sina is
            # a complete additional candidate signal, never an identity owner.
            # Partial Eastmoney pages remain raw evidence but cannot be used as
            # a complete cross-check or be silently interpreted as no change.
            hkex_residuals.extend({
                "code": candidate["code"],
                "reason": "sina_candidate_without_official_directory_identity",
                "provider_evidence_refs": [candidate["source_url"]],
            } for candidate in sina_rows if candidate["code"] not in official_codes)
            hkex_source_route_warnings.append({
                **hkex_eastmoney_failure,
                "treatment": "official_population_complete_sina_candidates_complete_eastmoney_candidates_not_reconciled",
                "candidate_count_from_partial_eastmoney_not_promoted": (
                    hkex_eastmoney_failure.get("partial_candidate_count_not_promoted")
                    if "partial_candidate_count_not_promoted" in hkex_eastmoney_failure
                    else sum(len(parse_eastmoney_hk_spot_payload(path.read_bytes()))
                             for path in hkex_eastmoney_targets)
                ),
            })
    unique = {(row.exchange, row.code): row for row in rows}
    if len(unique) != len(rows):
        raise ValueError("authoritative current state contains duplicate exchange/code rows")
    inventory = {
        "schema_version": "fr_a_share_user_triggered_authoritative_refresh_v1",
        "market_scope": config.market_scope,
        "requested_by": "user_update_intent",
        "as_of_date": config.as_of_date,
        "source_mode": config.source_mode,
        "route_counts": {
            "SSE": sum(row.exchange == "SSE" for row in rows),
            "SZSE": sum(row.exchange == "SZSE" for row in rows),
            "BSE": sum(row.exchange == "BSE" for row in rows),
            "HKEX": sum(row.exchange == "HKEX" for row in rows),
        },
        "hkex_identity_source": "HKEX_official_directory_with_accepted_reference" if hkex_target else "provider_candidate_only",
        "hkex_identity_reconciliation_residual_count": len(hkex_residuals),
        "hkex_identity_reconciliation_residuals": hkex_residuals,
        "hkex_provider_status": ("not_applicable" if not hong_kong_selected else
                                 "configured" if hkex_provider_configured else "unconfigured"),
        "hkex_candidate_observation": {
            "official_current_population_complete": hkex_target is not None,
            "sina_candidate_inventory_complete": hkex_sina_complete,
            "eastmoney_candidate_inventory_complete": hkex_eastmoney_complete,
            "eastmoney_completed_page_count": len(hkex_eastmoney_targets),
            "fallback_used": bool(hkex_source_route_warnings),
        },
        "source_route_warnings": hkex_source_route_warnings,
        "hkex_provider_unconfigured_gap": None if hkex_provider_configured or not hong_kong_selected else {
            "gap_type": "provider_unconfigured",
            "venue": "HKEX",
            "reason": "public HKEX candidate adapters require installation-local provider and rights configuration",
            "evidence_refs": [SINA_HK_SPOT_URL, EASTMONEY_HK_SPOT_URL],
        },
        "source_receipts": receipts,
        "result": "PASS",
    }
    current_state_path = config.output_root / "authoritative_current_state_v1.ndjson"
    current_state_path.write_text(
        "".join(
            canonical_json({
                "exchange": row.exchange,
                "code": row.code,
                "listing_date": row.listing_date,
                "security_name": row.security_name,
                "source_id": row.source_id,
                "share_type": row.share_type,
                "source_updated_date": _as_date(row.source_record.get("xxjsrq")) or None,
            }) + "\n"
            for row in sorted(rows, key=lambda item: (item.exchange, item.code))
        ),
        encoding="utf-8",
    )
    inventory["current_state_path"] = str(current_state_path)
    inventory["current_state_sha256"] = sha256_file(current_state_path)
    write_json_atomic(config.output_root / "authoritative_refresh_v1.json", inventory)
    return sorted(rows, key=lambda row: (row.exchange, row.code)), inventory, crosswalk_target


def _read_lifecycle(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def compare_authoritative_state(
    lifecycle_rows: Iterable[Mapping[str, Any]],
    current_rows: Iterable[CurrentListingRecord],
    *,
    baseline_date: str,
) -> dict[str, Any]:
    baseline: dict[tuple[str, str], dict[str, Any]] = {}
    for row in lifecycle_rows:
        start = row.get("listing_start_date")
        end = row.get("listing_end_date")
        if start and start > baseline_date:
            continue
        if end and end < baseline_date:
            continue
        aliases = row.get("code_aliases") or [{"code": row.get("security_code_at_cutoff"), "effective_from": start, "effective_to": end}]
        for alias in aliases:
            effective_from = alias.get("effective_from")
            effective_to = alias.get("effective_to")
            if effective_from and effective_from > baseline_date:
                continue
            if effective_to and effective_to < baseline_date:
                continue
            baseline[(str(row["exchange"]).upper(), normalize_listing_code(row["exchange"], alias["code"]))] = {
                "episode_evidence_key": str(row["episode_evidence_key"]),
                "security_name": str(row.get("security_name_at_cutoff") or row.get("security_name") or ""),
            }
    current = {(row.exchange, row.code): row for row in current_rows}
    added = []
    unresolved = []
    for key in sorted(set(current) - set(baseline)):
        row = current[key]
        finding = {"exchange": row.exchange, "code": row.code, "listing_date": row.listing_date,
                   "security_name": row.security_name, "source_id": row.source_id, "share_type": row.share_type}
        hkex_owner = accepted_hkex_change_or_none(row) if row.exchange == "HKEX" else None
        if hkex_owner is not None:
            added.append({
                **finding,
                **hkex_owner,
                "change_type": "accepted_current_hkex_security_requires_owner_onboarding",
                "financial_conclusion": "accepted current HKEX economic security absent from the installation owner",
            })
        elif row.exchange == "HKEX":
            unresolved.append({
                **finding,
                "change_type": "hkex_current_candidate_requires_accepted_identity_lifecycle",
                "reason": "HKEX current code presence without the accepted reference/lifecycle contract cannot establish identity",
            })
        elif (row.share_type == "B" and row.exchange in {"SSE", "SZSE"}
              and row.listing_date and row.listing_date < baseline_date):
            added.append({**finding, "change_type": "existing_security_requires_owner_onboarding",
                          "financial_conclusion": "official existing B-share; owner omission is not a new listing"})
        elif row.listing_date and row.listing_date >= baseline_date:
            added.append({**finding, "change_type": "authoritative_new_listing", "financial_conclusion": "new listing after baseline"})
        else:
            unresolved.append({**finding, "change_type": "newly_visible_requires_adjudication", "reason": "authoritative current row predates baseline; absence from baseline cannot prove a new listing"})
    for key in sorted(set(baseline) - set(current)):
        unresolved.append({"exchange": key[0], "code": key[1], "episode_evidence_key": baseline[key]["episode_evidence_key"], "change_type": "missing_from_current_requires_termination_evidence", "reason": "absence from a current list is not delisting evidence"})
    existing_subject_changes = []
    for key in sorted(set(baseline) & set(current)):
        old_name = baseline[key]["security_name"].strip()
        new_name = current[key].security_name.strip()
        if old_name and new_name and old_name != new_name:
            existing_subject_changes.append({
                "exchange": key[0],
                "code": key[1],
                "episode_evidence_key": baseline[key]["episode_evidence_key"],
                "change_type": "authoritative_security_name_change",
                "prior_security_name": old_name,
                "security_name": new_name,
                "effective_at": _as_date(current[key].source_record.get("xxjsrq")) or baseline_date,
                "source_id": current[key].source_id,
                "financial_conclusion": "same listing and instrument; authoritative current security-name alias changed",
            })
    result = {
        "schema_version": "fr_a_share_user_triggered_reality_diff_v1",
        "baseline_date": baseline_date,
        "baseline_active_alias_count": len(baseline),
        "authoritative_current_count": len(current),
        "unchanged_alias_count": len(set(baseline) & set(current)),
        "deterministic_new_listing_count": len(added),
        "unresolved_change_count": len(unresolved),
        "deterministic_changes": added,
        "existing_subject_change_count": len(existing_subject_changes),
        "existing_subject_changes": existing_subject_changes,
        "unresolved_changes": unresolved,
    }
    return result


def _provider_payload(config: UserUpdateConfig, name: str, fetcher: Callable[[Path], dict[str, Any]]) -> tuple[Path, dict[str, Any]]:
    target = config.output_root / "raw_source_evidence" / name
    if config.provider_replay_root:
        source = config.provider_replay_root / name
        if not source.is_file():
            family_prefix = name.split("_", 1)[0] + "_"
            code = next(iter(re.findall(r"(?<!\d)(\d{5,6})(?!\d)", name)), "")
            candidates = sorted(
                path for path in config.provider_replay_root.glob(f"{family_prefix}*")
                if path.is_file() and ".receipt." not in path.name and (not code or code in path.name)
            )
            source = candidates[0] if len(candidates) == 1 else source
        if source.is_file():
            return target, _copy_replay(source, target, name)
        raise FileNotFoundError(f"retained provider replay evidence missing for {name}")
    return target, fetcher(target)


def _provider_symbol(exchange: str, code: str) -> tuple[str, str]:
    prefix = {"SSE": "sh", "SZSE": "sz", "BSE": "bj"}[exchange]
    return f"{prefix}{code}", f"{prefix.upper()}{code}"


def _clean_title(value: Any) -> str:
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def classify_cninfo_event(title: str) -> dict[str, Any]:
    """Classify a source event by its financial meaning, not daily lag.

    Every announcement is a document.  Only an actual periodic report filing
    enters financial acquisition scope; meetings, inquiry replies, and generic
    references to a report remain document-only.  Trading-status/code/name
    notices additionally enter reality investigation scope.
    """
    clean = _clean_title(title)
    families = ["documents"]
    period_end = None
    filing = re.fullmatch(
        r"(?P<year>\d{4})年(?P<period>年度|半年度|第一季度|第三季度)报告"
        r"(?:摘要)?(?:[（(][^）)]*(?:修订|更正)[^）)]*[）)])?",
        clean,
    )
    if filing:
        year = filing.group("year")
        suffix = {
            "年度": "12-31",
            "半年度": "06-30",
            "第一季度": "03-31",
            "第三季度": "09-30",
        }[filing.group("period")]
        period_end = f"{year}-{suffix}"
        families.append("financial")
    if re.search(r"(?:继续)?停牌|复牌|证券简称|证券代码|终止上市|恢复上市|转板|吸收合并", clean):
        families.append("reality")
    return {
        "families": families,
        "financial_period_end": period_end,
        "is_correction": bool(re.search(r"修订|更正", clean)),
    }


def _announcement_date(milliseconds: Any) -> str | None:
    if milliseconds in (None, ""):
        return None
    # CNINFO timestamps are publication-midnight values in the China market
    # timezone (UTC+08:00), not UTC calendar dates.
    china_market_tz = timezone(timedelta(hours=8))
    return datetime.fromtimestamp(int(milliseconds) / 1000, tz=china_market_tz).date().isoformat()


def _failed_source_attempt(
    *,
    source_id: str,
    route: str,
    error: Exception,
    event_id: str | None = None,
    requested_scope: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "mode": "source_attempt",
        "route": route,
        "outcome": "failure",
        "error_type": type(error).__name__,
        "error": str(error),
        "event_id": event_id,
        "requested_scope": dict(requested_scope or {}),
        "proved_source_boundary": False,
        "economic_non_applicability": False,
    }


def discover_incremental_source_events(
    config: UserUpdateConfig,
    current_rows: Iterable[CurrentListingRecord],
    index: AcceptedChinaEquityEpisodeIndex,
    diff: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Discover CNINFO disclosures from a bounded overlap window.

    The predecessor cutoff initializes the first cursor.  Later runs retain a
    seven-day overlap and de-duplicate by announcement id, allowing legitimate
    late arrivals without replaying integrated events as new work.
    """
    if config.market_scope == "hong_kong":
        return [], {
            "schema_version": "fr_a_share_incremental_source_event_discovery_v1",
            "market_scope": "hong_kong",
            "route_status": "not_applicable_to_hong_kong",
            "receipt_count": 0, "receipts": [], "events": [],
            "resolved_event_count": 0, "unresolved_event_count": 0,
            "unresolved_events": [],
        }
    prior_state = dict(config.previous_update_state or {})
    prior_families = prior_state.get("family_state") or {}
    prior_dates = [
        str((prior_families.get(name) or {}).get("source_cursor_date") or "")
        for name in ("documents", "financial", "reality")
    ]
    cursor_date = max([value for value in prior_dates if value] or [config.baseline_reality_date])
    overlap_start = (date.fromisoformat(cursor_date) - timedelta(days=max(config.source_event_overlap_days - 1, 0))).isoformat()
    raw_root = config.output_root / "raw_source_evidence"
    raw_root.mkdir(parents=True, exist_ok=True)
    receipts: list[dict[str, Any]] = []
    payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []

    if config.source_mode == "replay":
        try:
            if config.source_event_replay_root is None:
                raise FileNotFoundError("source-event replay root is not configured")
            sources = sorted(config.source_event_replay_root.glob("cninfo_disclosure_feed_*.json"))
            if not sources:
                raise FileNotFoundError("retained CNINFO disclosure-feed evidence missing")
            for position, source in enumerate(sources, 1):
                target = raw_root / f"cninfo_disclosure_feed_{position:03d}.json"
                receipt = _copy_replay(source, target, "cninfo_disclosure_feed")
                receipt["outcome"] = "success"
                receipts.append(receipt)
                payloads.append((json.loads(target.read_text(encoding="utf-8")), receipt))
        except Exception as exc:
            receipts.append(_failed_source_attempt(
                source_id="cninfo_disclosure_feed",
                route="retained authoritative disclosure feed",
                error=exc,
                requested_scope={"from": overlap_start, "to": config.as_of_date},
            ))
    else:
        session = requests.Session()
        page = 1
        total_pages = 1
        while page <= total_pages:
            target = raw_root / f"cninfo_disclosure_feed_{page:03d}.json"
            form = {
                "stock": "", "tabName": "fulltext", "pageSize": "30", "pageNum": str(page),
                "column": "szse", "category": "", "plate": "", "trade": "",
                "seDate": f"{overlap_start}~{config.as_of_date}", "searchkey": "", "secid": "",
                "sortName": "", "sortType": "", "isHLtitle": "true",
            }
            try:
                receipt = _request(
                    session,
                    source_id="cninfo_disclosure_feed",
                    url="https://www.cninfo.com.cn/new/hisAnnouncement/query",
                    target=target,
                    method="POST",
                    data=form,
                    referer="https://www.cninfo.com.cn/",
                )
                receipt["outcome"] = "success"
                receipts.append(receipt)
                payload = json.loads(target.read_text(encoding="utf-8"))
                payloads.append((payload, receipt))
                total_pages = int(payload.get("totalpages") or payload.get("totalPages") or 1)
            except Exception as exc:
                receipts.append(_failed_source_attempt(
                    source_id="cninfo_disclosure_feed",
                    route="CNINFO full-market disclosure query",
                    error=exc,
                    requested_scope={"from": overlap_start, "to": config.as_of_date, "page": page},
                ))
                break
            page += 1

    candidates_by_code: dict[str, list[tuple[str, str | None, str]]] = {}
    for row in current_rows:
        if row.exchange == "HKEX":
            continue
        candidates_by_code.setdefault(row.code, []).append((row.exchange, None, "authoritative_current"))
    for change in (diff or {}).get("unresolved_changes", []):
        if change.get("change_type") != "missing_from_current_requires_termination_evidence":
            continue
        if str(change["exchange"]).upper() == "HKEX":
            continue
        code = normalize_listing_code(change["exchange"], change["code"])
        candidate = (str(change["exchange"]).upper(), str(change["episode_evidence_key"]), "predecessor_disappearance")
        if candidate not in candidates_by_code.setdefault(code, []):
            candidates_by_code[code].append(candidate)
    events_by_id: dict[str, dict[str, Any]] = {}
    unresolved: list[dict[str, Any]] = []
    initialized = any((prior_families.get(name) or {}).get("source_cursor_initialized") for name in ("documents", "financial", "reality"))
    for payload, receipt in payloads:
        for raw in payload.get("announcements") or []:
            event_id = str(raw.get("announcementId") or "")
            code = str(raw.get("secCode") or "").zfill(6)
            published = _announcement_date(raw.get("announcementTime"))
            if not event_id or not published or published > config.as_of_date:
                continue
            # The first continuing cursor starts at the predecessor's accepted
            # cutoff.  Subsequent overlaps admit unseen late-arriving ids.
            if not initialized and published <= config.baseline_reality_date:
                continue
            candidate_bindings: list[tuple[str, Any, str]] = []
            for exchange, expected_episode, context_role in candidates_by_code.get(code, []):
                try:
                    candidate_binding = index.resolve(exchange, code, published)
                except (KeyError, ValueError):
                    continue
                if expected_episode and candidate_binding.episode_evidence_key != expected_episode:
                    continue
                candidate_bindings.append((exchange, candidate_binding, context_role))
            unique = {
                (exchange, binding.episode_evidence_key): (exchange, binding, context_role)
                for exchange, binding, context_role in candidate_bindings
            }
            if not unique:
                unresolved.append({
                    "event_id": event_id, "code": code, "published_date": published,
                    "title": _clean_title(raw.get("announcementTitle")),
                    "reason": "disclosure code is not bound by current reality or a lifecycle-scoped predecessor disappearance",
                })
                continue
            if len(unique) != 1:
                unresolved.append({
                    "event_id": event_id, "code": code,
                    "published_date": published, "title": _clean_title(raw.get("announcementTitle")),
                    "reason": "multiple lifecycle-scoped predecessor/current bindings remain possible",
                    "candidate_episodes": sorted(episode for _, episode in unique),
                })
                continue
            exchange, binding, subject_context_role = next(iter(unique.values()))
            classification = classify_cninfo_event(str(raw.get("announcementTitle") or ""))
            events_by_id[event_id] = {
                "event_id": event_id,
                "exchange": exchange,
                "code": code,
                "security_name": str(raw.get("secName") or ""),
                "published_date": published,
                "title": _clean_title(raw.get("announcementTitle")),
                "source_url": "https://static.cninfo.com.cn/" + str(raw.get("adjunctUrl") or "").lstrip("/"),
                "source_response_hash": receipt.get("sha256"),
                "source_observation_key": stable_key("source_observation", {
                    "provider": "CNINFO", "announcement_id": event_id,
                    "response_hash": receipt.get("sha256"),
                }),
                "episode_evidence_key": binding.episode_evidence_key,
                "entity_id": binding.entity_id,
                "instrument_id": binding.instrument_id,
                "listing_id": binding.listing_id,
                "historical_subject_context_role": subject_context_role,
                **classification,
            }
    events = [events_by_id[key] for key in sorted(events_by_id, key=lambda key: (events_by_id[key]["published_date"], key))]
    summary = {
        "schema_version": "fr_a_share_incremental_source_event_discovery_v1",
        "predecessor_cutoff": config.baseline_reality_date,
        "source_cursor_date_before": cursor_date,
        "overlap_from": overlap_start,
        "through": config.as_of_date,
        "source_cursor_initialized_before": initialized,
        "receipt_count": len(receipts),
        "receipts": receipts,
        "resolved_event_count": len(events),
        "unresolved_event_count": len(unresolved),
        "events": events,
        "unresolved_events": unresolved,
        "predecessor_disappearance_candidate_count": sum(
            change.get("change_type") == "missing_from_current_requires_termination_evidence"
            for change in (diff or {}).get("unresolved_changes", [])
        ),
    }
    return events, summary


def _lifecycle_document(
    config: UserUpdateConfig,
    session: requests.Session,
    event: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    name = f"cninfo_document_{event['event_id']}.pdf"
    target = config.output_root / "raw_source_evidence" / name
    if config.source_event_replay_root is not None:
        source = config.source_event_replay_root / name
        if not source.is_file():
            raise FileNotFoundError(f"retained lifecycle document missing for event {event['event_id']}")
        receipt = _copy_replay(source, target, "cninfo_lifecycle_document")
        receipt["outcome"] = "success"
        receipt["event_id"] = event["event_id"]
        return target, receipt
    receipt = _request(
        session,
        source_id="cninfo_lifecycle_document",
        url=str(event["source_url"]),
        target=target,
        referer="https://www.cninfo.com.cn/",
    )
    receipt["outcome"] = "success"
    receipt["event_id"] = event["event_id"]
    return target, receipt


def extract_market_status_events(
    pdf_path: Path,
    event: Mapping[str, Any],
    *,
    as_of_date: str,
    document_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)
    return market_status_events_from_text(text, event, as_of_date=as_of_date, document_sha256=document_sha256)


def market_status_events_from_text(
    text: str, event: Mapping[str, Any], *, as_of_date: str, document_sha256: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Interpret explicit dated actions, never decision date as listing end."""
    compact = re.sub(r"\s+", "", text)
    findings: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    patterns = (
        ("trading_suspension", r"(?:自|将于|于)(\d{4})年(\d{1,2})月(\d{1,2})日[^。；]{0,45}?开市(?:时)?起(?:开始)?停牌"),
        ("trading_resumption", r"(?:自|将于|于)(\d{4})年(\d{1,2})月(\d{1,2})日[^。；]{0,45}?开市(?:时)?起复牌"),
        ("continued_suspension", r"自(\d{4})年(\d{1,2})月(\d{1,2})日[^。；]{0,45}?开市(?:时)?起继续停牌"),
        ("trading_suspension", r"停牌日期为(\d{4})年(\d{1,2})月(\d{1,2})日"),
        ("trading_suspension", r"股票将于(\d{4})年(\d{1,2})月(\d{1,2})日停牌(?:一天|1天)"),
        ("trading_resumption", r"自(\d{4})年(\d{1,2})月(\d{1,2})日起复牌交易"),
        ("trading_suspension", r"即(\d{4})年(\d{1,2})月(\d{1,2})日[）)]开市起停牌"),
    )
    seen: set[tuple[str, str]] = set()
    for event_type, pattern in patterns:
        for match in re.finditer(pattern, compact):
            effective = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            key = (event_type, effective)
            if key in seen:
                continue
            seen.add(key)
            date_role = "actual_market_status_effective" if effective <= as_of_date else "scheduled_future_market_status"
            finding = {
                "event_type": event_type,
                "effective_date": effective,
                "date_role": date_role,
                "source_announcement_id": event["event_id"],
                "source_url": event["source_url"],
                "source_document_sha256": document_sha256,
                "evidence_excerpt": match.group(0)[:240],
            }
            findings.append(finding)
            if date_role == "actual_market_status_effective":
                applied.append(finding)
    termination_patterns = (
        r"摘牌日期[：:](\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(?:将|已)?在?(\d{4})年(\d{1,2})月(\d{1,2})日(?:被)?摘牌",
        r"(?:自|将于)(\d{4})年(\d{1,2})月(\d{1,2})日起终止上市",
    )
    for pattern in termination_patterns:
        for match in re.finditer(pattern, compact):
            effective = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            key = ("listing_termination", effective)
            if key in seen:
                continue
            seen.add(key)
            date_role = "actual_listing_end" if effective <= as_of_date else "scheduled_future_listing_end"
            finding = {
                "event_type": "listing_termination",
                "effective_date": effective,
                "date_role": date_role,
                "source_announcement_id": event["event_id"],
                "source_url": event["source_url"],
                "source_document_sha256": document_sha256,
                "evidence_excerpt": match.group(0)[:240],
                "termination_mechanism": "exchange_delisting_after_final_termination_decision",
            }
            findings.append(finding)
            if date_role == "actual_listing_end":
                applied.append(finding)
    for match in re.finditer(r"最后交易日期(?:为)?(\d{4})年(\d{1,2})月(\d{1,2})日", compact):
        effective = f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
        key = ("last_trading_date", effective)
        if key in seen:
            continue
        seen.add(key)
        estimated = compact[max(0, match.start() - 2):match.start()] == "预计"
        role = ("scheduled_future_last_trading_date" if effective > as_of_date else
                "estimated_last_trading_date_unconfirmed" if estimated else "actual_last_trading_date")
        finding = {
            "event_type": "last_trading_date",
            "effective_date": effective,
            "date_role": role,
            "source_announcement_id": event["event_id"],
            "source_url": event["source_url"],
            "source_document_sha256": document_sha256,
            "evidence_excerpt": match.group(0)[:240],
        }
        findings.append(finding)
        if finding["date_role"] == "actual_last_trading_date":
            applied.append(finding)
    return applied, findings


def market_status_disposition(text: str, title: str, applied: list, findings: list) -> str:
    """A positive evidence classification; empty extraction alone stays open."""
    compact = re.sub(r"\s+", "", text)
    if applied:
        return "effective_changes"
    if any(r.get("date_role") == "estimated_last_trading_date_unconfirmed" for r in findings):
        return "unresolved"
    if findings:
        return "future_event"
    if re.search(r"(?:已于|已自)[^。]{0,60}(?:停牌|复牌|终止上市)|(?:实际|正式)(?:终止上市|摘牌)|(?:摘牌|终止上市)日期[：:]", compact):
        return "unresolved"
    if "拟变更" in title and re.search(r"尚需[^。]{0,90}(?:批准|审议|申请)", compact):
        return "no_new_effective_transition"
    if "风险提示" in title and "可能" in title and re.search(r"(?:可能|若|如)[^。]{0,70}(?:终止上市|强制退市)", compact):
        return "no_new_effective_transition"
    if "持股情况" in title and "停牌前" in compact:
        return "no_new_effective_transition"
    return "unresolved"


def market_status_related_codes(text: str) -> list[str]:
    """Only the explicit security-code header, never bond codes or body mentions."""
    compact = re.sub(r"\s+", "", text)
    header = re.search(r"证券代码[：:]([^。]{1,60}?)(?:证券简称|公告编号)", compact)
    return sorted(set(re.findall(r"(?<!\d)\d{6}(?!\d)", header.group(1)))) if header else []


def derive_incremental_scope(
    config: UserUpdateConfig,
    current_rows: Iterable[CurrentListingRecord],
    index: AcceptedChinaEquityEpisodeIndex,
    diff: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Derive daily work from canonical watermarks, never caller selections.

    Replay mode remains bounded to codes for which retained source responses are
    actually present.  The complete internally derived scope is still recorded;
    missing replay fixtures are not converted into business coverage states.
    """
    current_rows = list(current_rows)
    control = Path(resolve_equity_predecessor_control_dependency(config.predecessor_snapshot_id)["path"])
    daily_metrics = sorted(DAILY_METRIC_CONTRACT)
    new_keys = {
        (str(row["exchange"]).upper(), normalize_listing_code(row["exchange"], row["code"]))
        for row in diff["deterministic_changes"]
    }
    watermarks: dict[tuple[str, str], str | None] = {}
    unresolved: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    with closing(sqlite3.connect(f"{control.as_uri()}?mode=ro", uri=True)) as connection:
        for row in current_rows:
            key = (row.exchange, row.code)
            row_metrics = sorted(daily_metric_contract(
                exchange=row.exchange, code=row.code, share_type=row.share_type,
            ))
            hk_contract = (row.source_record.get("accepted_reference") or {}).get("daily_source_contract") or {}
            if row.exchange == "HKEX" and row.source_record.get("trading_currency") != "HKD":
                if (row.source_record.get("trading_currency") != "USD"
                        or hk_contract.get("quote_currency") != "USD"
                        or not hk_contract.get("sina_ohlcv_supported_from")):
                    unresolved.append({
                        "exchange": row.exchange, "code": row.code,
                        "reason": "accepted_identity_retained_but_non_hkd_daily_price_contract_unavailable",
                    })
                    continue
                row_metrics = sorted(set(row_metrics) - {"market.trade_amount"})
            binding = None
            try:
                binding = index.resolve(row.exchange, row.code, config.as_of_date)
            except KeyError:
                if key not in new_keys:
                    unresolved.append({
                        "exchange": row.exchange,
                        "code": row.code,
                        "reason": "authoritative current subject has no lifecycle-scoped canonical binding",
                    })
                    continue
            maxima: list[str] = []
            if binding is not None:
                found = connection.execute(
                    """
                    SELECT metric_id,max_date_or_period
                    FROM coverage_summary
                    WHERE universe IN ('a_share','CN_A_SHARE') AND subject_id=?
                      AND metric_id IN ({})
                    """.format(",".join("?" for _ in row_metrics)),
                    (binding.instrument_id, *row_metrics),
                ).fetchall()
                by_metric = {str(metric): value for metric, value in found}
                if all(by_metric.get(metric) for metric in row_metrics):
                    maxima = [str(by_metric[metric]) for metric in row_metrics]
            watermark = min(maxima) if maxima else None
            watermarks[key] = watermark
            if watermark and watermark >= config.as_of_date:
                continue
            start = row.listing_date or config.baseline_reality_date
            if row.exchange == "HKEX" and hk_contract.get("sina_ohlcv_supported_from"):
                start = max(start, str(hk_contract["sina_ohlcv_supported_from"]))
            if watermark:
                start = (date.fromisoformat(watermark) + timedelta(days=1)).isoformat()
            if start and start > config.as_of_date:
                continue
            candidates.append({
                "exchange": row.exchange,
                "code": row.code,
                "listing_date": row.listing_date,
                "security_name": row.security_name,
                "daily_from_date": start,
                "canonical_watermark": watermark,
                "expected_daily_metrics": row_metrics,
                "trading_currency": row.source_record.get("trading_currency"),
                "daily_source_contract": hk_contract,
                "change_type": "new_listing_and_incremental_data" if key in new_keys else "incremental_after_canonical_watermark",
            })

    selected = candidates
    replay_codes: set[str] = set()
    if config.provider_replay_root is not None:
        for pattern in ("tencent_*", "sina_hk_*"):
            for path in config.provider_replay_root.glob(pattern):
                if not path.is_file():
                    continue
                replay_codes.update(re.findall(r"(?<!\d)(\d{5,6})(?!\d)", path.name))
        selected = [row for row in candidates if row["code"] in replay_codes]
    summary = {
        "schema_version": "fr_a_share_user_triggered_scope_derivation_v1",
        "predecessor_snapshot_id": config.predecessor_snapshot_id,
        "as_of_date": config.as_of_date,
        "authoritative_current_count": len(current_rows),
        "daily_metric_count": len(daily_metrics),
        "watermark_affected_count": len(candidates),
        "selected_acquisition_count": len(selected),
        "bounded_replay_unexecuted_count": len(candidates) - len(selected),
        "replay_source_codes": sorted(replay_codes),
        "unresolved_binding_count": len(unresolved),
        "unresolved_bindings": unresolved,
        "selected_scope": selected,
        "derivation_basis": "authoritative current lifecycle plus predecessor canonical coverage watermarks",
    }
    return selected, summary


def build_internal_plan(
    config: UserUpdateConfig,
    lifecycle_rows: list[dict[str, Any]],
    identities: dict[str, Any],
    diff: dict[str, Any],
    acquisition_scope: list[dict[str, Any]],
    source_events: list[dict[str, Any]],
    event_discovery: Mapping[str, Any],
    crosswalk_path: Path,
    identity_state: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    hkex_provider_configured = _hkex_provider_configured(config)
    crosswalk = parse_cninfo_subject_crosswalk(crosswalk_path.read_text(encoding="utf-8"))
    identity_by_episode = {row["episode_evidence_key"]: row for row in identities["objects"]}
    lifecycle_by_episode = {row["episode_evidence_key"]: row for row in lifecycle_rows}
    index = AcceptedChinaEquityEpisodeIndex.load(config.lifecycle_path, config.identity_reconciliation_path)
    resolutions: list[dict[str, Any]] = []
    resolution_by_episode: dict[str, dict[str, Any]] = {}
    payload_writer = BoundedPlanPayloadWriter(config.output_root / "bounded_plan_payload_v1")
    daily_observation_count = 0
    daily_source_detail_count = 0
    financial_rows: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    reality_events: list[dict[str, Any]] = []
    financial_coverage: list[dict[str, Any]] = []
    lifecycle_evidence: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = list(event_discovery.get("receipts") or [])
    unresolved = list(diff["unresolved_changes"])
    session = requests.Session()
    previous_family_state = dict((config.previous_update_state or {}).get("family_state") or {})
    progress: dict[str, dict[str, Any]] = {}
    family_scope_counts = {"daily": len(acquisition_scope), "financial": 0, "documents": 0, "reality": 0}

    family_work: dict[str, dict[str, Any]] = {}
    for family in ("documents", "financial", "reality"):
        previous = dict(previous_family_state.get(family) or {})
        integrated = {
            str(row["event_id"]): dict(row)
            for row in previous.get("recent_integrated_events", [])
        }
        pending = {
            str(row["event_id"]): dict(row)
            for row in previous.get("pending_events", [])
        }
        family_work[family] = {"previous": previous, "integrated": integrated, "pending": pending}

    events_by_id = {str(row["event_id"]): dict(row) for row in source_events}
    for family in ("documents", "financial", "reality"):
        for pending in (family_work[family]["pending"].values() if config.market_scope != "hong_kong" else ()):
            event = pending.get("event")
            if event:
                events_by_id.setdefault(str(event["event_id"]), dict(event))
    org_change_counts: dict[str, int] = {}
    mainland_objects = None
    assignments_by_subject = {}
    accepted_mainland = []
    for change in diff["deterministic_changes"]:
        subject = crosswalk.get(change["code"])
        if subject and subject.get("orgId"):
            org_id = str(subject["orgId"])
            org_change_counts[org_id] = org_change_counts.get(org_id, 0) + 1

    hkex_resolutions, hkex_allocation_residuals = allocate_accepted_hkex_changes(
        identity_state,
        (change for change in diff["deterministic_changes"] if change["exchange"] == "HKEX"),
    )
    unresolved.extend(hkex_allocation_residuals)
    for resolution in hkex_resolutions.values():
        resolutions.append(resolution)
        resolution_by_episode[resolution["episode_evidence_key"]] = resolution

    for change in diff["deterministic_changes"]:
        exchange, code, listing_date = change["exchange"], change["code"], change["listing_date"]
        scope_coverage: list[dict[str, Any]] = []
        if exchange == "HKEX":
            continue
        subject = crosswalk.get(code)
        if not subject or not subject.get("orgId"):
            unresolved.append({**change, "change_type": "new_listing_identity_unresolved", "reason": "CNINFO issuer subject crosswalk absent"})
            continue
        org_id = str(subject["orgId"])
        existing_security = change.get("change_type") == "existing_security_requires_owner_onboarding"
        if existing_security and (subject.get("category") != "B股" or change.get("share_type") != "B"):
            raise ValueError("existing B-share onboarding lacks concordant official classification")
        if org_change_counts[org_id] > 1:
            unresolved.append({**change, "change_type": "parallel_new_listing_identity_unresolved", "reason": "multiple simultaneous codes for one issuer require share-class/counter adjudication"})
            continue
        episode_key = f"{exchange}:{code}:{listing_date}:current"
        accepted = identity_by_episode.get(episode_key)
        same_issuer_other_episode = [row for row in lifecycle_rows if str(row.get("issuer_external_key") or "") == org_id and row["episode_evidence_key"] != episode_key]
        if accepted is None and same_issuer_other_episode and not existing_security:
            unresolved.append({**change, "change_type": "new_listing_continuity_unresolved", "reason": "issuer already has another episode; board transfer, relisting, replacement, or parallel line must be adjudicated"})
            continue
        entity_key = f"cninfo_org:{org_id}"
        share_type = mainland_share_type(exchange, code, str(change.get("share_type") or "") or None)
        instrument_key = (f"cninfo_org:{org_id}:ordinary_a_share" if share_type == "A"
                          else f"cninfo_org:{org_id}:{exchange.lower()}_{share_type.lower()}_equity")
        if existing_security:
            collisions = [row for row in lifecycle_rows if row.get("exchange") == exchange
                          and any(str(alias.get("code")) == code for alias in row.get("code_aliases", []))]
            if collisions:
                unresolved.append({**change, "change_type": "existing_security_episode_collision",
                                   "reason": "existing code episode requires explicit continuity reconciliation"})
                continue
        if mainland_objects is None:
            assignments = identity_state.rows()
            assignments_by_subject = {row["subject_id"]: row for row in assignments}
            mainland_objects = {row.get("decision_attributes", {}).get("a_share_authoritative_owner_object_key"): row
                                for row in assignments}
            del assignments
        if existing_security and same_issuer_other_episode:
            issuer_ids = {identity_by_episode[row["episode_evidence_key"]]["entity_id"] for row in same_issuer_other_episode}
            if len(issuer_ids) != 1:
                raise ValueError("accepted issuer owner has competing economic entity assignments")
            issuer_id = next(iter(issuer_ids))
            assignment = assignments_by_subject.get(issuer_id)
            if assignment is None:
                raise ValueError("accepted issuer identity is absent from durable installation assignments")
            keyed = mainland_objects.get(f"entity:{entity_key}")
            if keyed is not None and keyed["subject_id"] != issuer_id:
                raise ValueError("durable object key conflicts with the accepted issuer UUID")
            # The accepted owner may predate this helper's object-key attribute.
            # Reuse its UUID; absence of that convenience key is not absence of
            # an economic entity and must not allocate a second issuer.
            mainland_objects[f"entity:{entity_key}"] = assignment
        accepted_mainland.append((change, entity_key, instrument_key, episode_key, share_type, accepted, existing_security, org_id))

    missing = {}
    for change, entity_key, instrument_key, episode_key, share_type, accepted, existing_security, org_id in accepted_mainland:
        for decision in discovered_listing_identity_decisions(entity_object_key=entity_key, instrument_object_key=instrument_key,
                episode_object_key=episode_key, exchange=change["exchange"], share_type=share_type,
                provenance_refs=[str(crosswalk_path), f"authoritative {change['exchange']} listing {change['code']} from {change['listing_date']}"]):
            key = decision["decision_attributes"]["a_share_authoritative_owner_object_key"]
            if key not in mainland_objects:
                missing[key] = decision
    if missing:
        created = identity_state.create_decisions_batch(missing.values())
        mainland_objects.update({row["decision_attributes"]["a_share_authoritative_owner_object_key"]: row for row in created})
    for change, entity_key, instrument_key, episode_key, share_type, accepted, existing_security, org_id in accepted_mainland:
        exchange, code, listing_date = change["exchange"], change["code"], change["listing_date"]
        allocation = ensure_discovered_listing_identity(
            identity_state, entity_object_key=entity_key, instrument_object_key=instrument_key,
            episode_object_key=episode_key, exchange=exchange, share_type=share_type,
            provenance_refs=[f"authoritative {exchange} listing {code} from {listing_date}", f"CNINFO org {org_id}"],
            existing_objects=mainland_objects,
        )
        objects = allocation["objects"]
        allocation["created_assignment_count"] = sum(key in missing for key in objects)
        allocation["reused_assignment_count"] = len(objects) - allocation["created_assignment_count"]
        resolution = {
            "schema_version": "fr_a_share_discovered_listing_identity_resolution_v1",
            "exchange": exchange, "code": code, "security_name": change["security_name"],
            "listing_start_date": listing_date, "listing_end_date": None, "lifecycle_status": "current",
            "episode_evidence_key": episode_key, "entity_object_key": entity_key, "instrument_object_key": instrument_key,
            "entity_id": objects[f"entity:{entity_key}"]["subject_id"],
            "instrument_id": objects[f"instrument:{instrument_key}"]["subject_id"],
            "listing_id": objects[f"listing:{episode_key}"]["subject_id"],
            "series": {family: objects[f"series:{episode_key}:{family}"]["subject_id"] for family in ("daily_ohlc", "market_trade_amount", "market_turnover_rate", "market_volume")},
            "created_assignment_count": allocation["created_assignment_count"], "reused_assignment_count": allocation["reused_assignment_count"],
            "provenance_refs": [str(config.output_root / "authoritative_refresh_v1.json"), str(crosswalk_path)],
            "share_type": share_type, "security_classification": "b_share" if share_type == "B" else "a_share",
            "trading_currency": ("USD" if exchange == "SSE" else "HKD") if share_type == "B" else "CNY",
            "owner_onboarding_action": "existing_security_onboarding" if existing_security else "new_listing_onboarding",
        }
        if accepted and (accepted["entity_id"], accepted["instrument_id"], accepted["listing_id"]) != (resolution["entity_id"], resolution["instrument_id"], resolution["listing_id"]):
            raise ValueError(f"durable identity conflicts with accepted episode {episode_key}")
        resolutions.append(resolution)
        resolution_by_episode[episode_key] = resolution

    for change in diff.get("existing_subject_changes", []):
        binding = index.resolve(change["exchange"], change["code"], config.as_of_date)
        accepted = identity_by_episode[binding.episode_evidence_key]
        accepted_lifecycle = lifecycle_by_episode[binding.episode_evidence_key]
        resolution = {
            "schema_version": "fr_a_share_existing_listing_state_resolution_v1",
            "exchange": binding.exchange,
            "code": binding.code,
            "security_name": change["security_name"],
            "prior_security_name": change["prior_security_name"],
            "name_effective_at": _as_date(change.get("effective_at")) or config.as_of_date,
            "listing_start_date": binding.listing_start_date,
            "listing_end_date": binding.listing_end_date,
            "lifecycle_status": binding.lifecycle_status,
            "episode_evidence_key": binding.episode_evidence_key,
            "entity_object_key": str(accepted_lifecycle["economic_entity_decision_key"]),
            "instrument_object_key": str(accepted_lifecycle["economic_instrument_decision_key"]),
            "entity_id": accepted["entity_id"],
            "instrument_id": accepted["instrument_id"],
            "listing_id": accepted["listing_id"],
            "series": {row["series_family"]: row["series_id"] for row in accepted["series"]},
            "created_assignment_count": 0,
            "reused_assignment_count": 7,
            "provenance_refs": [str(config.output_root / "authoritative_refresh_v1.json")],
        }
        resolutions.append(resolution)
        resolution_by_episode[binding.episode_evidence_key] = resolution

    # Source events are scoped independently from daily acquisition.  Their
    # lifecycle-scoped binding was established during discovery.
    for event_id in sorted(events_by_id, key=lambda key: (events_by_id[key]["published_date"], key)):
        event = events_by_id[event_id]
        for family in event.get("families") or ():
            work = family_work[family]
            processing_contract = SOURCE_FAMILY_PROCESSING_CONTRACTS[family]
            integrated_contract = (work["integrated"].get(event_id) or {}).get("processing_contract")
            if (
                event_id in work["integrated"]
                and event_id not in work["pending"]
                and integrated_contract == processing_contract
            ):
                continue
            if (family == "financial" and config.selected_data_families is not None
                    and not set(config.selected_data_families) & {"financial", "financial_statements", "financial_kpi"}):
                # Retain both the event and its last actual attempt. Not
                # selected is neither a provider failure nor integration.
                prior = work["pending"].get(event_id) or {}
                work["pending"][event_id] = {
                    **prior, "event_id": event_id, "event": event,
                    "deferred_reason": "data_family_not_selected",
                    "required_for_selected_scope": False,
                }
                continue
            family_scope_counts[family] += 1
            if family == "documents":
                try:
                    document_path, receipt = _lifecycle_document(config, session, event)
                    attempts.append(receipt)
                    documents.append({
                        "exchange": event["exchange"],
                        "code": event["code"],
                        "effective_at": event["published_date"],
                        "identity_effective_at": event["published_date"],
                        "announcement_id": event_id,
                        "title": event["title"],
                        "source_url": event["source_url"],
                        "source_response_hash": event["source_response_hash"],
                        "source_observation_key": event["source_observation_key"],
                        "asset_source_path": str(document_path),
                        "asset_sha256": receipt["sha256"],
                        "asset_byte_count": receipt["bytes"],
                        "mime_type": "application/pdf",
                        "processing_contract": processing_contract,
                    })
                    work["pending"].pop(event_id, None)
                    work["integrated"][event_id] = {
                        "event_id": event_id,
                        "published_date": event["published_date"],
                        "source_response_hash": event["source_response_hash"],
                        "processing_contract": processing_contract,
                    }
                except Exception as exc:
                    failure = _failed_source_attempt(
                        source_id="cninfo_document_asset",
                        route="CNINFO announcement document asset",
                        error=exc,
                        event_id=event_id,
                        requested_scope={"source_url": event.get("source_url")},
                    )
                    attempts.append(failure)
                    work["pending"][event_id] = {
                        "event_id": event_id,
                        "event": event,
                        "last_attempt": failure,
                    }
                continue

            if family == "financial":
                if config.source_mode == "live" and not installation_provider_route_enabled("sina_financial_statements"):
                    gap = {
                        "source_id": "sina_financial_statements",
                        "mode": "source_attempt",
                        "route": "Sina CompanyFinanceService.getFinanceReport2022",
                        "outcome": "provider_unconfigured",
                        "event_id": event_id,
                        "reason": "Sina financial-statement adapter requires installation-local provider and rights configuration",
                    }
                    attempts.append(gap)
                    work["pending"][event_id] = {"event_id": event_id, "event": event, "last_attempt": gap}
                    continue
                _, financial_symbol = _provider_symbol(event["exchange"], event["code"])
                try:
                    route_rows: dict[str, list[dict[str, Any]]] = {}
                    response_hashes: dict[str, str] = {}
                    for route, label in (("lrb", "income"), ("fzb", "balance"), ("llb", "cash_flow")):
                        financial_name = f"sina_{financial_symbol.lower()}_{label}.json"

                        def fetch_event_financial(target: Path, route: str = route, label: str = label) -> dict[str, Any]:
                            return _request(
                                session,
                                source_id=f"sina_{label}",
                                url="https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
                                target=target,
                                params={"paperCode": financial_symbol, "source": route, "type": "0", "page": "1", "num": "100"},
                            )

                        financial_path, receipt = _provider_payload(config, financial_name, fetch_event_financial)
                        receipt.update({"outcome": "success", "event_id": event_id, "statement_route": route})
                        attempts.append(receipt)
                        route_rows[route] = parse_sina_financial_response(financial_path.read_text(encoding="utf-8"))
                        response_hashes[route] = receipt["sha256"]
                    observations = financial_statement_observations(
                        route_rows,
                        exchange=event["exchange"],
                        code=event["code"],
                        period_end=event["financial_period_end"],
                        source_response_hashes=response_hashes,
                    )
                    if not observations:
                        raise ValueError(
                            f"successful financial statement responses have no usable accepted metrics for {event['financial_period_end']}"
                        )
                    for observation in observations:
                        observation["identity_effective_at"] = event["published_date"]
                        observation["source_document_id"] = event_id
                        if event.get("is_correction"):
                            observation["version_effective_scope"] = {
                                "filing_announcement_id": event_id,
                                "published_date": event["published_date"],
                                "revision_role": "corrected_filing",
                            }
                        financial_rows.append(observation)
                    returned_metrics = {row["metric_id"] for row in observations}
                    for metric_id in sorted(ACCEPTED_A_SHARE_FINANCIAL_METRICS):
                        usable = int(metric_id in returned_metrics)
                        financial_coverage.append({
                            "exchange": event["exchange"], "code": event["code"],
                            "effective_at": event["published_date"], "subject_role": "entity",
                            "metric_id": metric_id, "lifecycle_applicable": True,
                            "route_attempt_status": "success" if usable else "success_empty",
                            "retained_source_contract_boundary": None,
                            "requested_from": event["financial_period_end"], "requested_to": event["financial_period_end"],
                            "returned_economic_dates": [event["financial_period_end"]] if usable else [],
                            "usable_row_count": usable,
                            "evidence_basis": (
                                "CNINFO periodic filing event triggered all three governed Sina statement routes; "
                                "the accepted metric was mapped or derived from source-native fields"
                                if usable else
                                "CNINFO periodic filing event triggered all three governed Sina statement routes; "
                                "no usable source-native components were returned for this accepted metric"
                            ),
                        })
                    work["pending"].pop(event_id, None)
                    work["integrated"][event_id] = {
                        "event_id": event_id,
                        "published_date": event["published_date"],
                        "source_response_hash": event["source_response_hash"],
                        "processing_contract": processing_contract,
                        "accepted_metric_count": len(returned_metrics),
                    }
                except Exception as exc:
                    failure = _failed_source_attempt(
                        source_id="sina_financial_statements",
                        route="Sina CompanyFinanceService.getFinanceReport2022 income/balance/cash-flow routes",
                        error=exc,
                        event_id=event_id,
                        requested_scope={
                            "exchange": event["exchange"], "code": event["code"],
                            "period_end": event["financial_period_end"],
                        },
                    )
                    attempts.append(failure)
                    work["pending"][event_id] = {
                        "event_id": event_id,
                        "event": event,
                        "last_attempt": failure,
                    }
                continue

            if family == "reality":
                try:
                    document_path, receipt = _lifecycle_document(config, session, event)
                    attempts.append(receipt)
                    applied, findings = extract_market_status_events(
                        document_path,
                        event,
                        as_of_date=config.as_of_date,
                        document_sha256=receipt["sha256"],
                    )
                    lifecycle_evidence.append({
                        "event_id": event_id,
                        "exchange": event["exchange"], "code": event["code"],
                        "episode_evidence_key": event["episode_evidence_key"],
                        "entity_id": event["entity_id"], "instrument_id": event["instrument_id"],
                        "listing_id": event["listing_id"], "title": event["title"],
                        "document_receipt": receipt, "findings": findings,
                    })
                    document_text = "\n".join(page.extract_text() or "" for page in PdfReader(document_path).pages)
                    disposition = market_status_disposition(document_text, event["title"], applied, findings)
                    lifecycle_evidence[-1]["disposition"] = disposition
                    # An official future listing-termination day is product
                    # metadata, not an actual lifecycle end. Keep its source
                    # proof in the next immutable owner while the event stays
                    # pending for the later effective transition.
                    previous_events = lifecycle_by_episode[event["episode_evidence_key"]].get("market_status_events") or []
                    for finding in findings:
                        if finding.get("event_type") != "listing_termination" or finding.get("date_role") != "scheduled_future_listing_end":
                            continue
                        key = (finding["event_type"], finding["effective_date"], event_id)
                        if key in {
                            (old.get("event_type"), old.get("effective_date"), old.get("announcement_id"))
                            for old in previous_events
                        }:
                            continue
                        reality_events.append({
                            "episode_evidence_key": event["episode_evidence_key"],
                            "exchange": event["exchange"], "code": event["code"],
                            "entity_id": event["entity_id"], "instrument_id": event["instrument_id"],
                            "listing_id": event["listing_id"], "announcement_id": event_id,
                            "observed_at": event["published_date"], **finding,
                        })
                    if disposition == "future_event":
                        work["pending"][event_id] = {"event_id": event_id, "event": event,
                            "disposition": disposition, "findings": findings, "required_for_selected_scope": False}
                        continue
                    if disposition == "unresolved":
                        raise ValueError("authoritative lifecycle document yielded no actual status boundary at the update cutoff")
                    related = [event]
                    for code in market_status_related_codes(document_text):
                        if code == event["code"]:
                            continue
                        candidate = next((r for r in resolutions if r["code"] == code and r["exchange"] == event["exchange"]), None)
                        if candidate is None:
                            try:
                                other = index.resolve(event["exchange"], code, config.as_of_date)
                                candidate = {"code": code, "exchange": event["exchange"], "episode_evidence_key": other.episode_evidence_key,
                                    **{k: identity_by_episode[other.episode_evidence_key][k] for k in ("entity_id", "instrument_id", "listing_id")}}
                            except KeyError:
                                continue
                        if candidate["entity_id"] != event["entity_id"]:
                            raise ValueError("multi-security status notice conflicts with accepted issuer identity")
                        related.append({**event, **{k: candidate[k] for k in ("code", "exchange", "episode_evidence_key", "entity_id", "instrument_id", "listing_id")}})
                    for context in related:
                        for finding in applied:
                            reality_events.append({
                                "episode_evidence_key": context["episode_evidence_key"],
                                "exchange": context["exchange"], "code": context["code"],
                                "entity_id": context["entity_id"], "instrument_id": context["instrument_id"],
                                "listing_id": context["listing_id"], "announcement_id": event_id,
                                "observed_at": event["published_date"], **finding,
                            })
                    if any(
                        finding.get("event_type") == "listing_termination"
                        and finding.get("date_role") == "actual_listing_end"
                        for finding in applied
                    ):
                        unresolved = [
                            row for row in unresolved
                            if not (
                                row.get("change_type") == "missing_from_current_requires_termination_evidence"
                                and row.get("episode_evidence_key") == event["episode_evidence_key"]
                            )
                        ]
                    work["pending"].pop(event_id, None)
                    work["integrated"][event_id] = {
                        "event_id": event_id,
                        "published_date": event["published_date"],
                        "source_response_hash": event["source_response_hash"],
                        "processing_contract": processing_contract,
                        "disposition": disposition,
                    }
                    future = [r for r in findings if str(r.get("date_role", "")).startswith("scheduled_future_")
                              or r.get("date_role") == "estimated_last_trading_date_unconfirmed"]
                    if future:
                        unconfirmed = any(r.get("date_role") == "estimated_last_trading_date_unconfirmed" for r in future)
                        work["pending"][event_id] = {"event_id": event_id, "event": event,
                            "disposition": "unresolved" if unconfirmed else "future_event", "findings": future,
                            "required_for_selected_scope": unconfirmed}
                except Exception as exc:
                    failure = _failed_source_attempt(
                        source_id="cninfo_lifecycle_document",
                        route="CNINFO authoritative lifecycle document investigation",
                        error=exc,
                        event_id=event_id,
                        requested_scope={"exchange": event["exchange"], "code": event["code"]},
                    )
                    attempts.append(failure)
                    work["pending"][event_id] = {
                        "event_id": event_id,
                        "event": event,
                        "last_attempt": failure,
                    }
                    unresolved.append({
                        "event_id": event_id,
                        "exchange": event["exchange"], "code": event["code"],
                        "change_type": "existing_subject_reality_event_unresolved",
                        "reason": str(exc),
                    })

    recent_cutoff = (date.fromisoformat(config.as_of_date) - timedelta(days=max(config.source_event_overlap_days * 2, 14))).isoformat()
    for family, work in family_work.items():
        relevant_dates = [
            event["published_date"] for event in source_events if family in (event.get("families") or ())
        ]
        previous_cursor = str(work["previous"].get("source_cursor_date") or config.baseline_reality_date)
        integrated = [
            row for row in work["integrated"].values()
            if str(row.get("published_date") or "") >= recent_cutoff
        ]
        progress[family] = {
            "source_cursor_initialized": True,
            "source_cursor_date": max([previous_cursor, *relevant_dates]),
            "recent_integrated_events": sorted(integrated, key=lambda row: (row["published_date"], row["event_id"])),
            "pending_events": sorted(work["pending"].values(), key=lambda row: row["event_id"]),
        }

    for scope in acquisition_scope:
        exchange, code = scope["exchange"], scope["code"]
        # Coverage evidence belongs to this acquisition scope only.  Keeping
        # the accumulator outside this loop caused every later scope to
        # re-normalize all prior scopes' date lists, turning plan construction
        # into an avoidable O(n²) operation and inflating the retained plan.
        scope_coverage: list[dict[str, Any]] = []
        listing_date = scope["listing_date"]
        matching_change = next(
            (
                change for change in diff["deterministic_changes"]
                if change["exchange"] == exchange
                and normalize_listing_code(exchange, change["code"])
                == normalize_listing_code(exchange, code)
            ),
            None,
        )
        expected_episode_key = (
            episode_key_for_change(matching_change)
            if matching_change is not None
            else f"{exchange}:{code}:{listing_date}:current"
        )
        resolution = resolution_by_episode.get(expected_episode_key)
        if resolution is not None:
            episode_key = expected_episode_key
            binding_start = resolution["listing_start_date"]
        else:
            try:
                binding = index.resolve(exchange, code, config.as_of_date)
            except KeyError:
                # The discovery was intentionally withheld above because its
                # economic continuity was ambiguous.  Source acquisition must
                # not bypass that identity decision.
                continue
            episode_key = binding.episode_evidence_key
            binding_start = binding.listing_start_date
        if resolution is None:
            accepted = identity_by_episode[episode_key]
            accepted_lifecycle = lifecycle_by_episode[episode_key]
            entity_key = str(accepted_lifecycle["economic_entity_decision_key"])
            instrument_key = str(accepted_lifecycle["economic_instrument_decision_key"])
            resolution = {
                "exchange": exchange,
                "code": code,
                "security_name": scope["security_name"],
                "listing_start_date": binding_start,
                "listing_end_date": binding.listing_end_date,
                "lifecycle_status": binding.lifecycle_status,
                "episode_evidence_key": episode_key,
                "entity_object_key": entity_key,
                "instrument_object_key": instrument_key,
                "entity_id": accepted["entity_id"],
                "instrument_id": accepted["instrument_id"],
                "listing_id": accepted["listing_id"],
                "series": {row["series_family"]: row["series_id"] for row in accepted["series"]},
            }
        daily_from = scope["daily_from_date"]
        if exchange == "HKEX":
            if config.source_mode == "live" and not hkex_provider_configured:
                unresolved.append({
                    **scope, "change_type": "hkex_provider_unconfigured",
                    "reason": "HKEX daily adapter is available but no installation-local provider/rights configuration was supplied",
                    "provider_status": "unconfigured",
                })
                continue
            quote_currency = str(scope.get("trading_currency") or "")
            usd_contract = scope.get("daily_source_contract") or {}
            if quote_currency != "HKD" and (
                quote_currency != "USD" or usd_contract.get("quote_currency") != "USD"
                or not usd_contract.get("sina_ohlcv_supported_from")
            ):
                unresolved.append({
                    **scope, "change_type": "hkex_daily_source_contract_unavailable",
                    "reason": "accepted identity is retained but no USD price/volume time regime is proved",
                })
                continue
            daily_name = f"sina_hk_{code}_{daily_from}_{config.as_of_date}.js"

            def fetch_daily(target: Path) -> dict[str, Any]:
                return _request(
                    session, source_id="sina_hk_daily_unadjusted",
                    url=f"https://finance.sina.com.cn/stock/hkstock/{code}/klc2_kl.js",
                    target=target,
                )

            daily_path, daily_receipt = _provider_payload(config, daily_name, fetch_daily)
            attempts.append(daily_receipt)
            scope_key = f"{exchange}:{code}:{daily_from}:{config.as_of_date}"
            completed_scope = payload_writer.completed_scope(scope_key, daily_receipt["sha256"])
            if completed_scope is not None:
                daily_observation_count += int(completed_scope["daily_observation_count"])
                daily_source_detail_count += int(completed_scope["daily_source_detail_count"])
                continue
            parsed_daily = [
                row for row in decode_sina_hk_daily_payload(daily_path.read_bytes())
                if daily_from <= row["date"] <= config.as_of_date
            ]
            observations = sina_hk_daily_observations(
                parsed_daily, code=code, listing_id=resolution["listing_id"],
                response_sha256=daily_receipt["sha256"],
                quote_currency=quote_currency,
                supported_from="0000-01-01" if quote_currency == "HKD" else str(usd_contract["sina_ohlcv_supported_from"]),
                promote_amount=quote_currency == "HKD",
            )
            source_details = sina_hk_daily_source_details(
                parsed_daily, code=code, listing_id=resolution["listing_id"],
                response_sha256=daily_receipt["sha256"],
                supported_from="0000-01-01" if quote_currency == "HKD" else str(usd_contract["sina_ohlcv_supported_from"]),
                promote_amount=quote_currency == "HKD",
            )
            share_type = "HKEX_EQUITY"
        else:
            subject = crosswalk.get(code)
            if not subject or not subject.get("orgId"):
                unresolved.append({**scope, "change_type": "incremental_subject_route_unresolved", "reason": "CNINFO issuer subject crosswalk absent"})
                continue
            provider_symbol, _ = _provider_symbol(exchange, code)
            daily_name = f"tencent_{provider_symbol}_{daily_from}_{config.as_of_date}.json"

            def fetch_daily(target: Path) -> dict[str, Any]:
                params = {"_var": f"kline_day{config.as_of_date[:4]}", "param": f"{provider_symbol},day,{daily_from},{config.as_of_date},640,", "r": "0.8205512681390605"}
                return _request(session, source_id="tencent_daily_unadjusted", url="https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get", target=target, params=params)

            daily_path, daily_receipt = _provider_payload(config, daily_name, fetch_daily)
            attempts.append(daily_receipt)
            scope_key = f"{exchange}:{code}:{daily_from}:{config.as_of_date}"
            completed_scope = payload_writer.completed_scope(scope_key, daily_receipt["sha256"])
            if completed_scope is not None:
                daily_observation_count += int(completed_scope["daily_observation_count"])
                daily_source_detail_count += int(completed_scope["daily_source_detail_count"])
                continue
            parsed_daily = [row for row in parse_tencent_daily_response(daily_path.read_text(encoding="utf-8"), code, expected_adjustment_basis="unadjusted", expected_jsonp_variable=f"kline_day{config.as_of_date[:4]}") if daily_from <= row["trade_date"] <= config.as_of_date]
            share_type = mainland_share_type(exchange, code)
            observations = daily_observations(
                parsed_daily, exchange=exchange, code=code, listing_id=resolution["listing_id"],
                source_response_hash=daily_receipt["sha256"], share_type=share_type,
            )
            source_details = daily_source_details(
                parsed_daily, exchange=exchange, code=code, listing_id=resolution["listing_id"],
                source_response_hash=daily_receipt["sha256"], share_type=share_type,
            )
        for row in observations:
            row["identity_effective_at"] = listing_date
        for row in source_details:
            row["identity_effective_at"] = listing_date
        returned_metrics = {row["metric_id"] for row in observations}
        for metric in sorted(returned_metrics or daily_metric_contract(exchange=exchange, code=code, share_type=share_type)):
            provider_label = "Sina HK daily" if exchange == "HKEX" else "Tencent day"
            scope_coverage.append({"exchange": exchange, "code": code, "effective_at": config.as_of_date, "subject_role": "instrument", "metric_id": metric, "lifecycle_applicable": True, "route_attempt_status": "success" if returned_metrics else "success_empty", "retained_source_contract_boundary": None, "requested_from": daily_from, "requested_to": config.as_of_date, "returned_economic_dates": sorted({row["economic_time"] for row in observations}), "usable_row_count": sum(row["metric_id"] == metric for row in observations), "evidence_basis": f"authoritative current listing and explicit unadjusted {provider_label} response" if returned_metrics else f"authoritative current listing; successful {provider_label} response contained no usable row for the requested economic date"})
        if source_details:
            for metric_id in sorted({row.get("metric_id") or "market.trade_amount" for row in source_details}):
                relevant = [row for row in source_details if (row.get("metric_id") or "market.trade_amount") == metric_id]
                boundary = ("Sina non-HKD native field/date or zero-OHLC row not proved for standard facts"
                            if exchange == "HKEX" else
                            "Tencent field8 retained as source detail; native amount currency/scale is not proved for this B-share venue/time regime")
                scope_coverage.append({"exchange": exchange, "code": code, "effective_at": config.as_of_date, "subject_role": "instrument", "metric_id": metric_id, "lifecycle_applicable": True, "route_attempt_status": "semantic_unresolved", "retained_source_contract_boundary": boundary, "requested_from": daily_from, "requested_to": config.as_of_date, "returned_economic_dates": sorted({row["economic_time"] for row in relevant}), "usable_row_count": 0, "source_detail_count": len(relevant), "evidence_basis": "exact provider response retained without standard-fact promotion"})
        compact_coverage = []
        for evidence in scope_coverage:
            row = dict(evidence)
            dates = sorted(set(row.pop("returned_economic_dates", []) or []))
            row["returned_economic_date_count"] = len(dates)
            row["returned_economic_min"] = dates[0] if dates else None
            row["returned_economic_max"] = dates[-1] if dates else None
            row["returned_economic_dates_sha256"] = hashlib.sha256(canonical_json(dates).encode("utf-8")).hexdigest()
            compact_coverage.append(row)
        scope_summary = payload_writer.append_scope(
            scope_key=scope_key,
            source_sha256=daily_receipt["sha256"],
            daily_observations=observations,
            daily_source_details=source_details,
            coverage_evidence=compact_coverage,
        )
        daily_observation_count += int(scope_summary["daily_observation_count"])
        daily_source_detail_count += int(scope_summary["daily_source_detail_count"])

    previous_progress = {
        family: {
            key: value for key, value in dict(previous_family_state.get(family) or {}).items()
            if key in {"source_cursor_initialized", "source_cursor_date", "recent_integrated_events", "pending_events"}
        }
        for family in ("documents", "financial", "reality")
    }
    if config.market_scope == "hong_kong":
        # CNINFO disclosure cursors are Mainland-owned.  An HK-only check
        # neither processes old Mainland pending events nor advances their
        # progress merely because the shared Equity component changed.
        progress = {family: dict(value) for family, value in previous_progress.items()}

    def progress_signature(value: Mapping[str, Any]) -> dict[str, Any]:
        """Compare durable source progress, not retry diagnostics.

        A pending event is still unresolved when a retry changes only the
        diagnostic route/error (for example, a retained document is absent on
        one replay and yields no lifecycle boundary on another).  Such a
        retry has not advanced the source cursor, integrated the event, or
        changed the unresolved set, so it must not manufacture a material
        update.  Successful resolution is still observable because the event
        leaves ``pending_events`` and enters ``recent_integrated_events``.
        """
        result: dict[str, Any] = {
            "source_cursor_initialized": bool(value.get("source_cursor_initialized")),
            "source_cursor_date": value.get("source_cursor_date"),
            "recent_integrated_events": [
                {
                    "event_id": row.get("event_id"),
                    "published_date": row.get("published_date"),
                    "source_response_hash": row.get("source_response_hash"),
                    "processing_contract": row.get("processing_contract"),
                }
                for row in value.get("recent_integrated_events", [])
            ],
            "pending_events": [
                {
                    "event_id": row.get("event_id"),
                    "event": {
                        "event_id": (row.get("event") or {}).get("event_id"),
                        "published_date": (row.get("event") or {}).get("published_date"),
                        "source_response_hash": (row.get("event") or {}).get("source_response_hash"),
                    },
                }
                for row in value.get("pending_events", [])
            ],
        }
        result["recent_integrated_events"].sort(key=lambda row: (str(row.get("published_date") or ""), str(row.get("event_id") or "")))
        result["pending_events"].sort(key=lambda row: str(row.get("event_id") or ""))
        return result

    source_progress_changed = canonical_json(
        {family: progress_signature(previous_progress[family]) for family in previous_progress}
    ) != canonical_json(
        {family: progress_signature(progress[family]) for family in progress}
    )
    material = {
        "chain_contract": "continuous_canonical_update_v4_domain_closure",
        "baseline": config.predecessor_snapshot_id,
        "as_of": config.as_of_date,
        "diff": diff,
        "scope": acquisition_scope,
        "source_events": source_events,
        "source_progress": progress,
        "source_inputs": [
            {
                "source_id": row.get("source_id"), "outcome": row.get("outcome", "success"),
                "sha256": row.get("sha256"), "event_id": row.get("event_id"),
            }
            for row in attempts
        ],
    }
    suffix = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()[:12]
    successor_id = f"frashareuserupdate1_{config.as_of_date.replace('-', '')}T000000Z_{suffix}"
    bounded_payload = payload_writer.finalize()
    bounded_payload["root_relative_path"] = "bounded_plan_payload_v1"
    bounded_payload["coverage_evidence_relative_path"] = "coverage_evidence.ndjson.gz"
    plan = {
        "schema_version": "fr_a_share_discovery_acquisition_update_plan_v1",
        # A retry of the same discovered reality/source inputs must produce the
        # same internal plan hash.  Wall-clock request receipt time belongs in
        # source receipts, not in the canonical transaction identity.
        "created_at_utc": f"{config.as_of_date}T00:00:00Z",
        "user_request": {"intent": "update_a_share", "caller_supplied_semantic_parameters": 0},
        "discovery_evidence_path": str(config.output_root / "reality_diff_v1.json"),
        "source_route_evidence_path": str(config.output_root / "source_route_execution_v1.json"),
        "scope_derivation_evidence_path": str(config.output_root / "data_scope_derivation_v1.json"),
        "lifecycle_owner_path": str(config.lifecycle_path),
        "identity_reconciliation_path": str(config.identity_reconciliation_path),
        "identity_resolutions": resolutions,
        "predecessor_snapshot_id": config.predecessor_snapshot_id,
        "successor_snapshot_id": successor_id,
        "predecessor_control_path": resolve_equity_predecessor_control_dependency(config.predecessor_snapshot_id)["path"],
        "predecessor_control_dependency": resolve_equity_predecessor_control_dependency(config.predecessor_snapshot_id),
        "successor_control_path": str(resolve_unpublished_control_path(successor_id)),
        "daily_observations": [],
        "daily_source_details": [],
        "bounded_daily_payload": bounded_payload,
        "financial_observations": financial_rows,
        "documents": documents,
        "coverage_evidence": {"storage": "bounded_daily_payload", "count": bounded_payload["coverage_evidence_count"] + len(financial_coverage)},
        "financial_coverage_evidence": financial_coverage,
        "existing_subject_reality_events": reality_events,
        "source_event_progress": progress,
        "source_progress_changed": source_progress_changed,
        "reality_change_count": len(diff["deterministic_changes"]) + len(diff.get("existing_subject_changes", [])) + len(reality_events),
    }
    source_result = {
        "schema_version": "fr_a_share_user_triggered_source_execution_v1",
        "attempt_count": len(attempts),
        "attempts": attempts,
        "daily_observation_count": daily_observation_count,
        "daily_source_detail_count": daily_source_detail_count,
        "financial_observation_count": len(financial_rows),
        "document_count": len(documents),
        "reality_event_count": len(reality_events),
        "lifecycle_evidence": lifecycle_evidence,
        "source_event_discovery": dict(event_discovery),
        "source_event_progress": progress,
        "source_progress_changed": source_progress_changed,
        "family_scope_counts": family_scope_counts,
        "unresolved_changes": unresolved,
    }
    return plan, source_result


def _market_required_check(
    config: UserUpdateConfig,
    refresh: Mapping[str, Any],
    scope_result: Mapping[str, Any],
    event_discovery: Mapping[str, Any],
    sources: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    missing: list[str] = []
    if config.market_scope == "hong_kong":
        if refresh.get("hkex_provider_unconfigured_gap"):
            missing.append("hkex_daily_provider_route_unconfigured")
        if not refresh.get("hkex_candidate_observation", {}).get("official_current_population_complete"):
            missing.append("hkex_official_current_population_incomplete")
        if not refresh.get("hkex_candidate_observation", {}).get("sina_candidate_inventory_complete"):
            missing.append("hkex_required_candidate_inventory_incomplete")
        if not refresh.get("route_counts", {}).get("HKEX"):
            missing.append("hkex_official_population_empty")
        official_residuals = {
            "new_exchange_row_not_in_release_reference",
            "current_exchange_row_changed_from_release_reference",
            "release_reference_economic_security_absent_from_current_exchange_directory",
        }
        if any(row.get("reason") in official_residuals for row in
               refresh.get("hkex_identity_reconciliation_residuals") or []):
            # The official directory was read, but current economic state is
            # not reconciled.  Secondary candidate differences remain warnings.
            missing.append("hkex_official_population_identity_reconciliation_incomplete")
    elif config.market_scope == "mainland_china":
        if any(not refresh.get("route_counts", {}).get(venue) for venue in ("SSE", "SZSE", "BSE")):
            missing.append("mainland_official_venue_population_empty")
        if not any(row.get("source_id") == "sse_current_b" for row in refresh.get("source_receipts", [])):
            missing.append("sse_b_share_current_route_missing")
        receipts = list(event_discovery.get("receipts") or [])
        if not receipts or any(row.get("outcome") != "success" for row in receipts):
            missing.append("mainland_required_disclosure_index_incomplete")
    if scope_result.get("bounded_replay_unexecuted_count"):
        missing.append("selected_daily_scope_not_fully_executed")
    if sources is not None:
        for attempt in sources.get("attempts") or []:
            if attempt.get("source_id") in {"tencent_daily_unadjusted", "sina_hk_daily_unadjusted"} and attempt.get("outcome") not in {None, "success"}:
                missing.append("required_daily_route_incomplete")
        unresolved = list(sources.get("unresolved_changes") or [])
        contradiction_types = {
            "parallel_new_listing_identity_unresolved",
            "new_listing_continuity_unresolved",
            "existing_security_episode_collision",
        }
        if any(row.get("change_type") in contradiction_types for row in unresolved):
            raise ValueError("Equity market identity/episode contradiction prevents shared successor publication")
        if any(row.get("change_type") == "existing_subject_reality_event_unresolved" for row in unresolved):
            missing.append("required_lifecycle_evidence_unresolved")
    return {
        "schema_version": "fr_equity_market_required_check_v1",
        "market_scope": config.market_scope,
        "as_of_date": config.as_of_date,
        "required_route_receipts": refresh.get("source_receipts", []),
        "disclosure_receipts": event_discovery.get("receipts", []),
        "source_execution_attempt_count": len(sources.get("attempts") or []) if sources is not None else None,
        "unresolved_change_count": len(sources.get("unresolved_changes") or []) if sources is not None else None,
        "required_route_complete": not missing,
        "incomplete_reasons": sorted(set(missing)),
        "stage": "after_acquisition" if sources is not None else "before_acquisition",
    }


def run_user_triggered_update(
    config: UserUpdateConfig,
    *,
    identity_state: Any,
    materialize: Callable[[Path, Path], dict[str, Any]],
) -> dict[str, Any]:
    config.output_root.mkdir(parents=True, exist_ok=True)
    current_rows, refresh, crosswalk_path = refresh_authoritative_state(config)
    lifecycle = [row for row in _read_lifecycle(config.lifecycle_path)
                 if str(row.get("exchange") or "").upper() in _selected_exchanges(config)]
    identities = json.loads(config.identity_reconciliation_path.read_text(encoding="utf-8"))
    index = AcceptedChinaEquityEpisodeIndex.load(config.lifecycle_path, config.identity_reconciliation_path)
    diff = compare_authoritative_state(lifecycle, current_rows, baseline_date=config.baseline_reality_date)
    write_json_atomic(config.output_root / "reality_diff_v1.json", diff)
    acquisition_scope, scope_result = derive_incremental_scope(config, current_rows, index, diff)
    write_json_atomic(config.output_root / "data_scope_derivation_v1.json", scope_result)
    source_events, event_discovery = discover_incremental_source_events(config, current_rows, index, diff)
    write_json_atomic(config.output_root / "source_event_discovery_v1.json", event_discovery)
    if config.market_scope is not None:
        preliminary = _market_required_check(config, refresh, scope_result, event_discovery)
        if not preliminary["required_route_complete"]:
            write_json_atomic(config.output_root / "market_required_check_v1.json", preliminary)
            raise MarketCheckIncomplete(config.market_scope, preliminary["incomplete_reasons"])
    plan, sources = build_internal_plan(
        config,
        lifecycle,
        identities,
        diff,
        acquisition_scope,
        source_events,
        event_discovery,
        crosswalk_path,
        identity_state,
    )
    write_json_atomic(config.output_root / "source_route_execution_v1.json", sources)
    if config.market_scope is not None:
        check = _market_required_check(config, refresh, scope_result, event_discovery, sources)
        write_json_atomic(config.output_root / "market_required_check_v1.json", check)
        if not check["required_route_complete"]:
            raise MarketCheckIncomplete(config.market_scope, check["incomplete_reasons"])
    plan_path = config.output_root / "internal_update_plan_v1.json"
    write_json_atomic(plan_path, plan)
    plan_hash = sha256_file(plan_path)
    legacy_transaction_root = config.output_root / "canonical_transaction"
    legacy_result_path = legacy_transaction_root / "continuing_update_result_v1.json"
    if legacy_result_path.is_file() and json.loads(legacy_result_path.read_text(encoding="utf-8")).get("plan_sha256") == plan_hash:
        transaction_root = legacy_transaction_root
    else:
        transaction_root = config.output_root / "canonical_transactions" / plan["successor_snapshot_id"]
    no_op = (
        not plan.get("reality_change_count", 0)
        and bounded_payload_count(plan, "daily_observations") == 0
        and not plan["financial_observations"]
        and not plan["documents"]
        and not int((plan.get("coverage_evidence") or {}).get("count", 0))
        and not plan.get("source_progress_changed")
    )
    result = ({
        "schema_version": "fr_a_share_foundation_continuing_update_result_v1",
        "plan_sha256": plan_hash,
        "predecessor_snapshot_id": config.predecessor_snapshot_id,
        "successor_snapshot_id": None,
        "no_op": True,
        "active_pointer_modified": False,
        "result": "PASS",
    } if no_op else materialize(plan_path, transaction_root))
    proof = {
        "schema_version": "fr_a_share_user_triggered_update_result_v1",
        "request": {"intent": "update_a_share", "caller_supplied_semantic_parameters": 0},
        "authoritative_refresh": refresh,
        "reality_diff": diff,
        "data_scope_derivation": scope_result,
        "derived_scope": {
            "identity_resolution_count": len(plan["identity_resolutions"]),
            "daily_observation_count": bounded_payload_count(plan, "daily_observations"),
            "daily_source_detail_count": bounded_payload_count(plan, "daily_source_details"),
            "financial_observation_count": len(plan["financial_observations"]),
            "document_count": len(plan["documents"]),
            "existing_subject_reality_event_count": len(plan.get("existing_subject_reality_events", [])),
            "pending_source_event_count": sum(
                len(row.get("pending_events", []))
                for row in plan.get("source_event_progress", {}).values()
            ),
            "coverage_evidence_count": int((plan.get("coverage_evidence") or {}).get("count", 0)),
        },
        "source_execution": sources,
        "canonical_transaction": result,
        "canonical_transaction_evidence_path": str(transaction_root),
        "successor_snapshot_id": plan["successor_snapshot_id"],
        "publication_state": "unpublished",
        "background_scheduler_created": False,
        "result": "PASS" if result.get("result") == "PASS" else "FAIL",
    }
    write_json_atomic(config.output_root / "user_triggered_update_result_v1.json", proof)
    return proof


def config_from_environment(project_root: Path) -> UserUpdateConfig:
    default_runtime = resolve_temporary_workspace_path("china_equity_user_update")
    source_root = os.environ.get("FR_A_SHARE_UPDATE_AUTHORITATIVE_ROOT")
    provider_root = os.environ.get("FR_A_SHARE_UPDATE_PROVIDER_ROOT")
    event_root = os.environ.get("FR_A_SHARE_UPDATE_SOURCE_EVENT_ROOT")
    return UserUpdateConfig(
        project_root=project_root,
        output_root=Path(os.environ.get("FR_A_SHARE_UPDATE_OUTPUT_ROOT", default_runtime)),
        # The validated-head owner replaces both paths before acquisition.
        # Environment variables support compatibility drills and explicitly
        # bound same-day continuation of an interrupted live observation.
        # They never select an older validated head or financial identity owner.
        lifecycle_path=Path(os.environ.get("FR_A_SHARE_UPDATE_LIFECYCLE_PATH", "__validated_head_reality_owner__")),
        identity_reconciliation_path=Path(os.environ.get("FR_A_SHARE_UPDATE_IDENTITY_PATH", "__validated_head_identity_owner__")),
        # Normal execution replaces these placeholders from the compact
        # validated update head.  They are deliberately not environment- or
        # caller-selectable semantic inputs.
        predecessor_snapshot_id="validated_head_required",
        baseline_reality_date="validated_head_required",
        as_of_date=os.environ.get("FR_A_SHARE_UPDATE_AS_OF_DATE", date.today().isoformat()),
        source_mode=os.environ.get("FR_A_SHARE_UPDATE_SOURCE_MODE", "live"),
        authoritative_replay_root=Path(source_root) if source_root else None,
        provider_replay_root=Path(provider_root) if provider_root else None,
        source_event_replay_root=Path(event_root) if event_root else None,
    )
