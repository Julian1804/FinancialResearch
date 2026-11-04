"""User-triggered, reality-first incremental update for China Public Fund.

The caller supplies only update intent.  This owner reads the validated Fund
head, derives watermarks from manifest-backed locators, refreshes regulator and
exchange state, acquires only post-watermark observations, and stages one
immutable unpublished successor.  Codes remain scoped aliases; accepted FR
subjects and Series are resolved from the snapshot control database.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
import os
import shutil
import sqlite3
from contextlib import closing
import subprocess
import tempfile
import threading
import time
import urllib.parse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq
import requests
from openpyxl import load_workbook
from requests.adapters import HTTPAdapter

from backend.app.core.snapshot_manifest import clone_snapshot_from_manifest, reconcile_manifest_aggregate_counts
from backend.app.core.artifact_io import canonical_json, sha256_file, stable_key, write_json_atomic
from backend.app.core.source_transport import append_response_receipt, retain_bytes_once, sha256_bytes
from backend.app.core.validated_update_repository import (
    StaleUpdateHead,
    ValidatedUpdateHead,
    ValidatedUpdateRepository,
)
from backend.app.core.china_public_fund_foundation import (
    EID_BASE,
    SZSE_CATALOGS,
    _szse_code,
    _szse_name,
    parse_fund_detail_html,
)
from backend.app.core.china_public_fund_canonical_materialization import (
    DATASET_ID,
    DATASET_NAME,
    DOMAIN,
    FundTarget,
    canonical_fact_row,
    canonical_source_row,
)
from backend.app.core.china_public_fund_query_index import (
    ensure_fund_query_schema,
    rebuild_fund_search_index,
    replace_nonpromoted_interval_index,
    write_fund_search_delta,
)
from backend.app.core.incremental_control import (
    IncrementalControlView,
    add_subject_overrides,
    add_tombstones,
    base_checkpoint_snapshot_id,
    control_member_hash,
    ensure_control_watermark_schema,
    initialize_delta,
)
from backend.app.core.semantic_control import (
    canonical_alias_record,
    canonical_locator_record,
    canonical_relationship_record,
    ensure_semantic_control_schema,
    register_locators_batch,
)
from backend.app.core.storage_profile import (
    resolve_active_snapshot_pointer,
    resolve_identity_state_backup_root,
    resolve_identity_state_path,
    resolve_unpublished_control_path,
    resolve_unpublished_snapshot_path,
)
from backend.app.core.subject_identity import InstallationIdentityState
from backend.app.core.writer_runtime_ownership import (
    InstallationWriterLease,
    acquire_writer_lease,
    inspect_fund_recovery_candidate,
    write_runtime_owner_marker,
)
from backend.app.core.runtime_artifact_lifecycle import terminal_disposal_contract
from backend.app.core.szse_fund_lifecycle import (
    SZSEFundLifecycleError,
    SZSEFundLifecycleSource,
    SZSEFundLifecycleUnresolved,
)


UNIVERSE = "CN_PUBLIC_FUND"
FUND_CONTROL = "metadata/china_public_fund/fr_china_public_fund_control_v1.sqlite"
FUND_REALITY = "metadata/china_public_fund/authoritative_reality_owner_v1.json"
FUND_STATE = "metadata/china_public_fund/validated_update_state_v1.json"
FUND_IDENTITY = "metadata/china_public_fund/authoritative_identity_owner_v1.json"
MANIFEST = "metadata/corrected_candidate_manifest_v1.json"
EID_VALUATION_URL = f"{EID_BASE}/getPublicFundJZInfoMore.do"
TENCENT_KLINE_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
UPDATE_LOCK = threading.Lock()

NAV_METRICS = ("fund.nav", "fund.accumulated_nav")
LISTED_METRICS = ("market.close_price", "market.volume", "market.trade_amount")
ALL_METRICS = NAV_METRICS + LISTED_METRICS
MAX_CONTROL_CHAIN_DEPTH = 12
FULL_CONTROL_CHECKPOINT_DELTA_RATIO = 0.25
SZSE_CURL_RETRY_ATTEMPTS = 3
SZSE_CURL_RETRY_DELAY_SECONDS = 1.5
SZSE_CATALOG_RESTART_ATTEMPTS = 2
SZSE_ALL_FUND_CATALOG = "1000_lf"
SZSE_WORKBOOK_KINDS = {"ETF": "etf", "LOF": "lof", "不动产基金": "public_reit"}


class FundUpdateError(RuntimeError):
    pass


class FundSourceContractError(FundUpdateError):
    """An authoritative route returned content that cannot be interpreted safely."""


class FundSourceTransportError(FundUpdateError):
    """A required authoritative source could not be read after bounded retries."""


class FundCatalogConsistencyError(FundSourceContractError):
    """A catalog changed or could not be proven coherent during one acquisition."""


class FundPopulationCompletenessError(FundSourceContractError):
    """A valid source envelope cannot support a complete population conclusion."""


class FundIdentityReviewRequired(FundUpdateError):
    """A newly observed object needs accepted economic identity evidence."""


@dataclass(frozen=True)
class FundUpdateConfig:
    output_root: Path
    as_of_date: str
    request_timeout_seconds: int = 180
    source_workers: int = 16
    tencent_overlap_calendar_days: int = 7
    failpoint: str | None = None
    writer_control_path: Path | None = None
    # None retains the pre-Stage-B ordinary Fund behavior. A configured
    # installation freezes the selected families at the outer Update owner.
    selected_data_families: tuple[str, ...] | None = None


@dataclass(frozen=True)
class FundUpdateContext:
    head: ValidatedUpdateHead
    predecessor_root: Path
    control_path: Path
    watermarks: Mapping[tuple[str, str, str], str]
    share_class_bindings: Mapping[tuple[str, str], Mapping[str, str]]
    listing_bindings: Mapping[tuple[str, str], Mapping[str, str]]
    series_bindings: Mapping[tuple[str, str, str], str]
    new_subjects: tuple[Mapping[str, Any], ...] = ()
    new_aliases: tuple[Mapping[str, Any], ...] = ()
    new_relationships: tuple[Mapping[str, Any], ...] = ()
    identity_changes: tuple[Mapping[str, Any], ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_ndjson(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_ndjson(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(canonical_json(dict(row)) + "\n")
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def _manifest_entry(path: Path, root: Path, layer_name: str, row_count: int, created_at: str) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    digest = sha256_file(path)
    schema = pq.ParquetFile(path).schema_arrow if path.suffix == ".parquet" else path.suffix
    return {
        "partition_id": hashlib.sha256(canonical_json({"layer_name": layer_name, "relative_path": relative}).encode()).hexdigest(),
        "layer_name": layer_name,
        "relative_path": relative,
        "row_count": int(row_count),
        "byte_count": path.stat().st_size,
        "schema_sha256": hashlib.sha256(str(schema).encode()).hexdigest(),
        "content_sha256": digest,
        "completed": True,
        "created_at_utc": created_at,
    }


def _date_chunks(start: str, end: str, days: int = 7) -> list[tuple[str, str]]:
    cursor, finish = date.fromisoformat(start), date.fromisoformat(end)
    chunks: list[tuple[str, str]] = []
    while cursor <= finish:
        chunk_end = min(finish, cursor + timedelta(days=days - 1))
        chunks.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return chunks


def _eid_ao_data(start: str, end: str, offset: int, length: int, *, fund_code: str = "") -> str:
    return canonical_json([
        {"name": "sEcho", "value": 1}, {"name": "iColumns", "value": 5},
        {"name": "sColumns", "value": ",,,,"}, {"name": "iDisplayStart", "value": offset},
        {"name": "iDisplayLength", "value": length}, {"name": "fundType", "value": "all"},
        {"name": "fundCompanyShortName", "value": ""}, {"name": "fundCode", "value": fund_code},
        {"name": "fundName", "value": ""}, {"name": "startDate", "value": start},
        {"name": "endDate", "value": end},
    ])


class PublicFundSourceClient:
    """Free public-source adapter with immutable request receipts."""

    def __init__(self, root: Path, *, timeout: int = 180, session: requests.Session | None = None, cache_search_root: Path | None = None):
        self.root = root
        self.timeout = timeout
        self.session = session or requests.Session()
        if session is None:
            self.session.mount("https://", HTTPAdapter(pool_connections=32, pool_maxsize=32))
        self.calls: list[dict[str, Any]] = []
        self.catalog_sessions: list[dict[str, Any]] = []
        self._szse_use_curl = False
        self.cache_search_root = cache_search_root
        self.root.mkdir(parents=True, exist_ok=True)

    def _record(self, *, route: str, url: str, started: float, response: requests.Response | None, error: Exception | None = None) -> None:
        append_response_receipt(
            self.calls,
            route=route,
            url=url,
            started=started,
            response=response,
            error=error,
        )

    def _retain_response(self, relative: Path, payload: bytes) -> str:
        try:
            retain_bytes_once(self.root, relative, payload, conflict_error=FundSourceContractError)
        except FundSourceContractError as exc:
            raise FundSourceContractError(
                f"retained source response changed in place: {relative.as_posix()}"
            ) from exc
        return relative.as_posix()

    @staticmethod
    def _mapping_payload(value: Any, route: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise FundSourceContractError(f"{route} response is not a JSON object")
        return value

    @staticmethod
    def _list_member(payload: Mapping[str, Any], member: str, route: str) -> list[Any]:
        if member not in payload or not isinstance(payload[member], list):
            raise FundSourceContractError(f"{route} response lacks required list member {member}")
        return list(payload[member])

    def csrc_valuations(self, start: str, end: str, *, page_size: int = 10_000, fund_code: str = "") -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for chunk_start, chunk_end in _date_chunks(start, end):
            offset = 0
            while True:
                params = {"aoData": _eid_ao_data(chunk_start, chunk_end, offset, page_size, fund_code=fund_code)}
                payload = None
                for attempt in range(1, 4):
                    started = time.monotonic(); response = None
                    try:
                        response = self.session.get(
                            EID_VALUATION_URL, params=params,
                            headers={"User-Agent": "Mozilla/5.0 FR China Public Fund update", "Referer": f"{EID_BASE}/fund_value_search.html", "X-Requested-With": "XMLHttpRequest"},
                            timeout=self.timeout,
                        )
                        response.raise_for_status()
                        candidate = self._mapping_payload(response.json(), "CSRC_EID_public_fund_valuation")
                        page = self._list_member(candidate, "aaData", "CSRC_EID_public_fund_valuation")
                        if not all(isinstance(row, Mapping) for row in page):
                            raise FundSourceContractError("CSRC_EID_public_fund_valuation contains a non-object row")
                        if not any(key in candidate for key in ("iTotalRecords", "iTotalDisplayRecords")):
                            raise FundSourceContractError("CSRC_EID_public_fund_valuation lacks a total-record field")
                        payload = candidate
                        self._record(route="CSRC_EID_public_fund_valuation", url=response.url, started=started, response=response)
                        cache_name = (
                            f"csrc_valuation_{chunk_start}_{chunk_end}_"
                            f"{fund_code or 'all'}_{offset}_{hashlib.sha256(response.content).hexdigest()[:12]}.json"
                        )
                        cache_path = self.root / cache_name
                        if not cache_path.exists():
                            cache_path.write_bytes(response.content)
                        self.calls[-1]["retained_response_file"] = cache_name
                        break
                    except Exception as exc:
                        self._record(route="CSRC_EID_public_fund_valuation", url=EID_VALUATION_URL, started=started, response=response, error=exc)
                        if attempt == 3: raise
                assert payload is not None
                page = payload["aaData"]
                rows.extend(page)
                total = int(payload.get("iTotalRecords") or payload.get("iTotalDisplayRecords") or len(page))
                if offset + len(page) >= total or not page:
                    break
                offset += len(page)
        return rows

    def sse_listings(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_no = 1
        expected_total: int | None = None
        expected_pages: int | None = None
        while expected_pages is None or page_no <= expected_pages:
            params = {
                "isPagination": "true", "sqlId": "COMMON_JJZWZ_JJLB_L",
                "pageHelp.pageSize": "2000", "pageHelp.pageNo": str(page_no),
                "pageHelp.beginPage": str(page_no), "pageHelp.endPage": str(page_no),
                "CATEGORY": "F000", "type": "inParams", "CATEGORY_ASC": "1",
            }
            url = "https://query.sse.com.cn/commonQuery.do?" + urllib.parse.urlencode(params)
            started = time.monotonic(); response = None
            try:
                response = self.session.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://etf.sse.com.cn/fundlist/"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = self._mapping_payload(response.json(), "SSE_current_fund_list")
                result = self._list_member(payload, "result", "SSE_current_fund_list")
                page = payload.get("pageHelp")
                if not isinstance(page, Mapping):
                    raise FundSourceContractError("SSE_current_fund_list lacks pageHelp completeness metadata")
                try:
                    total = int(page["total"])
                    page_count = int(page["pageCount"])
                    reported_page = int(page["pageNo"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise FundSourceContractError(
                        "SSE_current_fund_list has invalid pagination completeness metadata"
                    ) from exc
                page_data = page.get("data")
                if not isinstance(page_data, list) or len(page_data) != len(result):
                    raise FundSourceContractError(
                        "SSE_current_fund_list result and pageHelp.data disagree"
                    )
                if reported_page != page_no or page_count < 0 or total < 0:
                    raise FundSourceContractError("SSE_current_fund_list pagination is inconsistent")
                if total == 0 or page_count == 0:
                    raise FundPopulationCompletenessError(
                        "SSE_current_fund_list is structurally valid but reports an implausible empty Fund population"
                    )
                if expected_total is None:
                    expected_total, expected_pages = total, page_count
                elif (total, page_count) != (expected_total, expected_pages):
                    raise FundSourceContractError(
                        "SSE_current_fund_list pagination totals changed during refresh"
                    )
                if not all(isinstance(row, Mapping) and row.get("FUND_CODE") for row in result):
                    raise FundSourceContractError("SSE_current_fund_list contains a row without FUND_CODE")
                rows.extend(dict(row) for row in result)
                self._record(route="SSE_current_fund_list", url=url, started=started, response=response)
                digest = hashlib.sha256(response.content).hexdigest()
                self.calls[-1]["retained_response_file"] = self._retain_response(
                    Path("sse_current") / f"page_{page_no:04d}_{digest[:12]}.json",
                    response.content,
                )
            except Exception as exc:
                self._record(route="SSE_current_fund_list", url=url, started=started, response=response, error=exc)
                raise
            page_no += 1
        if expected_total is None or len(rows) != expected_total:
            raise FundPopulationCompletenessError(
                "SSE_current_fund_list did not deliver its declared complete population"
            )
        return rows

    def _fetch_szse_page(
        self, *, kind: str, catalog: str, page: int, phase: str,
    ) -> tuple[Any, bytes]:
        """Read one official page without mixing transport attempts into state."""
        url = "https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&" + urllib.parse.urlencode({
            "CATALOGID": catalog, "TABKEY": "tab1", "PAGENO": page,
        })
        route = f"SZSE_current_fund_list_{kind}"
        if not self._szse_use_curl:
            started = time.monotonic(); response = None
            try:
                response = self.session.get(
                    url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.szse.cn/"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                self._validate_szse_page(payload, kind)
                self._record(route=route, url=url, started=started, response=response)
                self.calls[-1].update({"acquisition_phase": phase, "transport": "requests", "attempts": 1})
                return payload, response.content
            except Exception as exc:
                self._record(route=route, url=url, started=started, response=response, error=exc)
                self.calls[-1].update({"acquisition_phase": phase, "transport": "requests", "attempts": 1})
                self._szse_use_curl = True

        # The SZSE endpoint can terminate Python/OpenSSL sessions on Windows.
        # curl is only a transport fallback; it is not a second financial source.
        curl_started = time.monotonic()
        completed = None
        curl_error = ""
        for attempt in range(1, SZSE_CURL_RETRY_ATTEMPTS + 1):
            completed = subprocess.run(
                [
                    "curl.exe", "--http1.1", "--silent", "--show-error", "--fail-with-body",
                    "--location", "--max-time", str(self.timeout),
                    "--header", "User-Agent: Mozilla/5.0",
                    "--header", "Referer: https://www.szse.cn/", url,
                ],
                capture_output=True, check=False, timeout=self.timeout + 10,
            )
            if completed.returncode == 0:
                try:
                    payload = json.loads(completed.stdout.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    curl_error = f"invalid JSON response: {exc}"
                else:
                    self._validate_szse_page(payload, kind)
                    self.calls.append({
                        "route": route, "url": url, "http_status": 200,
                        "response_bytes": len(completed.stdout),
                        "response_sha256": hashlib.sha256(completed.stdout).hexdigest(),
                        "elapsed_seconds": round(time.monotonic() - curl_started, 3),
                        "result": "success", "transport": "curl_http1_fallback",
                        "attempts": attempt, "acquisition_phase": phase, "error": None,
                    })
                    return payload, completed.stdout
            else:
                curl_error = completed.stderr.decode("utf-8", errors="replace").strip()
            if attempt < SZSE_CURL_RETRY_ATTEMPTS:
                time.sleep(SZSE_CURL_RETRY_DELAY_SECONDS * attempt)
        raise FundSourceTransportError(
            "SZSE current Fund list transport failed after requests and curl retries: "
            + (curl_error or "empty response")
        )

    @staticmethod
    def _normalized_szse_rows(kind: str, rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, str]]:
        return sorted((kind, str(row["code"]), str(row.get("name") or "")) for row in rows)

    def _fetch_szse_catalog_once(
        self, *, kind: str, catalog: str, phase: str,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        page = 1
        expected_record_count: int | None = None
        expected_page_count: int | None = None
        page_numbers: list[int] = []
        seen_codes: set[str] = set()
        while expected_page_count is None or page <= expected_page_count:
            payload, raw_payload = self._fetch_szse_page(
                kind=kind, catalog=catalog, page=page, phase=phase,
            )
            metadata = payload[0]["metadata"]
            page_count = int(metadata["pagecount"])
            record_count = int(metadata["recordcount"])
            reported_page = int(metadata["pageno"])
            if reported_page != page:
                raise FundSourceContractError(
                    f"SZSE_current_fund_list_{kind} returned page {reported_page} while requesting {page}"
                )
            if expected_record_count is None:
                expected_record_count, expected_page_count = record_count, page_count
            elif (record_count, page_count) != (expected_record_count, expected_page_count):
                raise FundCatalogConsistencyError(
                    f"SZSE_current_fund_list_{kind} pagination totals changed during {phase}"
                )
            page_numbers.append(page)
            for item in payload[0].get("data") or []:
                code = _szse_code(item)
                if code in seen_codes:
                    raise FundSourceContractError(
                        f"SZSE_current_fund_list_{kind} contains duplicate Fund code {code}"
                    )
                seen_codes.add(code)
                rows.append({"kind": kind, "code": code, "name": _szse_name(item), "raw": item})
            digest = hashlib.sha256(raw_payload).hexdigest()
            retained = self._retain_response(
                Path("szse_current") / f"{kind}_{phase}_page_{page:04d}_{digest[:12]}.json",
                raw_payload,
            )
            self.calls[-1]["retained_response_file"] = retained
            page += 1
        if expected_record_count is None or len(rows) != expected_record_count:
            raise FundPopulationCompletenessError(
                f"SZSE_current_fund_list_{kind} did not deliver its declared complete population"
            )
        normalized = self._normalized_szse_rows(kind, rows)
        normalized_sha256 = hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()
        return {
            "kind": kind, "catalog_id": catalog, "record_count": expected_record_count,
            "page_count": expected_page_count, "page_numbers": page_numbers,
            "duplicate_code_count": 0, "normalized_sha256": normalized_sha256,
            "normalized_rows": normalized, "rows": rows,
        }

    def _fetch_szse_official_bytes(self, *, host: str, catalog: str, workbook: bool, phase: str) -> bytes:
        suffix = "ShowReport" if workbook else "ShowReport/data"
        params = {"SHOWTYPE": "xlsx" if workbook else "JSON", "CATALOGID": catalog, "TABKEY": "tab1"}
        if not workbook:
            params["PAGENO"] = "1"
        url = f"https://{host}/api/report/{suffix}?" + urllib.parse.urlencode(params)
        route = f"SZSE_current_fund_{'workbook' if workbook else 'metadata'}_{catalog}"
        last_error = ""
        for attempt in range(1, SZSE_CURL_RETRY_ATTEMPTS + 1):
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    ["curl.exe", "--http1.1", "--silent", "--show-error", "--fail-with-body",
                     "--location", "--max-time", str(self.timeout), "--header", "User-Agent: Mozilla/5.0",
                     "--header", f"Referer: https://{host}/", url],
                    capture_output=True, check=False, timeout=self.timeout + 10,
                )
                if completed.returncode == 0 and completed.stdout:
                    payload = completed.stdout
                    digest = hashlib.sha256(payload).hexdigest()
                    extension = "xlsx" if workbook else "json"
                    retained = self._retain_response(
                        Path("szse_current") / f"{catalog}_{phase}_{digest[:12]}.{extension}", payload,
                    )
                    self.calls.append({"route": route, "url": url, "result": "success", "http_status": 200,
                                       "transport": "curl_http1", "attempts": attempt, "acquisition_phase": phase,
                                       "response_bytes": len(payload), "response_sha256": digest,
                                       "retained_response_file": retained,
                                       "elapsed_seconds": round(time.monotonic() - started, 3)})
                    return payload
                last_error = completed.stderr.decode("utf-8", errors="replace").strip() or f"curl exit {completed.returncode}"
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            self.calls.append({"route": route, "url": url, "result": "failure", "transport": "curl_http1",
                               "attempts": attempt, "acquisition_phase": phase, "error": last_error,
                               "elapsed_seconds": round(time.monotonic() - started, 3)})
            if attempt < SZSE_CURL_RETRY_ATTEMPTS:
                time.sleep(SZSE_CURL_RETRY_DELAY_SECONDS * attempt)
        raise FundSourceTransportError(f"{route} failed after bounded retries: {last_error}")

    @staticmethod
    def _szse_workbook_rows(payload: bytes, *, catalog: str) -> list[dict[str, Any]]:
        try:
            workbook = load_workbook(BytesIO(payload), read_only=True, data_only=True)
            if len(workbook.worksheets) != 1:
                raise FundSourceContractError(f"SZSE workbook {catalog} has multiple sheets")
            sheet = workbook.active
            # SZSE exports a false <dimension ref="A1"/> despite containing all rows.
            sheet.reset_dimensions()
            values = sheet.iter_rows(values_only=True)
            header = tuple(str(item or "").strip() for item in next(values))
            expected = ("基金代码", "基金简称", "基金类别") if catalog == SZSE_ALL_FUND_CATALOG else ("证券代码", "证券简称")
            if header[:len(expected)] != expected:
                raise FundSourceContractError(f"SZSE workbook {catalog} has unexpected columns")
            rows: list[dict[str, Any]] = []
            seen: set[str] = set()
            for cells in values:
                if not any(item is not None and str(item).strip() for item in cells):
                    continue
                code = str(cells[0] or "").strip()
                name = str(cells[1] or "").strip()
                if not re.fullmatch(r"\d{6}", code) or not name or code in seen:
                    raise FundSourceContractError(f"SZSE workbook {catalog} has invalid/duplicate code or missing name: {code}")
                seen.add(code)
                row = {"code": code, "name": name, "raw": dict(zip(header, cells))}
                if catalog == SZSE_ALL_FUND_CATALOG:
                    kind = SZSE_WORKBOOK_KINDS.get(str(cells[2] or "").strip())
                    if kind is None:
                        raise FundSourceContractError(f"SZSE workbook has unsupported Fund category for {code}")
                    row["kind"] = kind
                rows.append(row)
            workbook.close()
        except (OSError, ValueError, StopIteration) as exc:
            raise FundSourceContractError(f"SZSE workbook {catalog} cannot be parsed") from exc
        if not rows:
            raise FundPopulationCompletenessError(f"SZSE workbook {catalog} has empty population")
        return rows

    @staticmethod
    def _szse_metadata(payload: bytes, *, catalog: str) -> tuple[int, str]:
        try:
            item = json.loads(payload.decode("utf-8"))[0]
            metadata = item["metadata"]
            if str(metadata["catalogid"]) != catalog or str(metadata["excel"]).lower() != "xlsx":
                raise ValueError("catalog or export contract mismatch")
            count = int(metadata["recordcount"])
            observed = date.fromisoformat(str(metadata["subname"]))
            if count <= 0:
                raise ValueError("empty population")
            return count, observed.isoformat()
        except (IndexError, KeyError, TypeError, ValueError, UnicodeError) as exc:
            raise FundSourceContractError(f"SZSE metadata {catalog} lacks current export completeness contract") from exc

    def _szse_listings_workbook(self) -> list[dict[str, Any]]:
        """One complete official export, checked against its own and category catalogs."""
        all_rows = self._szse_workbook_rows(
            self._fetch_szse_official_bytes(host="fund.szse.cn", catalog=SZSE_ALL_FUND_CATALOG,
                                            workbook=True, phase="all_initial"), catalog=SZSE_ALL_FUND_CATALOG,
        )
        count, observed = self._szse_metadata(
            self._fetch_szse_official_bytes(host="fund.szse.cn", catalog=SZSE_ALL_FUND_CATALOG,
                                            workbook=False, phase="all_metadata"), catalog=SZSE_ALL_FUND_CATALOG,
        )
        if len(all_rows) != count:
            raise FundCatalogConsistencyError("SZSE all-Fund workbook disagrees with official record count")
        categories: dict[str, dict[str, Any]] = {}
        for kind, catalog in SZSE_CATALOGS.items():
            rows = self._szse_workbook_rows(
                self._fetch_szse_official_bytes(host="www.szse.cn", catalog=catalog,
                                                workbook=True, phase=f"{kind}_category"), catalog=catalog,
            )
            category_count, category_date = self._szse_metadata(
                self._fetch_szse_official_bytes(host="www.szse.cn", catalog=catalog,
                                                workbook=False, phase=f"{kind}_metadata"), catalog=catalog,
            )
            own_codes = {row["code"] for row in rows}
            all_codes = {row["code"] for row in all_rows if row["kind"] == kind}
            if len(rows) != category_count or own_codes != all_codes or category_date != observed:
                raise FundCatalogConsistencyError(f"SZSE {kind} export/count/date/code coverage disagrees with all-Fund catalog")
            categories[kind] = {"catalog_id": catalog, "record_count": category_count,
                                "normalized_code_sha256": hashlib.sha256(canonical_json(sorted(own_codes)).encode()).hexdigest()}
        repeat = self._szse_workbook_rows(
            self._fetch_szse_official_bytes(host="fund.szse.cn", catalog=SZSE_ALL_FUND_CATALOG,
                                            workbook=True, phase="all_completion_recheck"), catalog=SZSE_ALL_FUND_CATALOG,
        )
        normalized = self._normalized_szse_rows("all", all_rows)
        digest = hashlib.sha256(canonical_json(normalized).encode()).hexdigest()
        if normalized != self._normalized_szse_rows("all", repeat):
            raise FundCatalogConsistencyError("SZSE all-Fund workbook changed during completion recheck")
        self.catalog_sessions = [{"route": "official_workbook", "authority": "SZSE", "catalog_id": SZSE_ALL_FUND_CATALOG,
                                  "record_count": count, "as_of_date": observed, "normalized_sha256": digest,
                                  "categories": categories, "complete": True}]
        return all_rows

    def szse_listings(self) -> list[dict[str, Any]]:
        try:
            return self._szse_listings_workbook()
        except FundSourceTransportError as primary_error:
            # Separate official category exports provide a bounded second route.
            # Never fall back on a semantic/count discrepancy.
            try:
                return self._szse_listings_category_workbooks()
            except FundSourceTransportError as fallback_error:
                raise FundSourceTransportError(
                    f"SZSE all-Fund and category workbook routes failed: {primary_error}; {fallback_error}"
                ) from fallback_error

    def _szse_listings_category_workbooks(self) -> list[dict[str, Any]]:
        total, observed = self._szse_metadata(
            self._fetch_szse_official_bytes(host="fund.szse.cn", catalog=SZSE_ALL_FUND_CATALOG,
                                            workbook=False, phase="category_fallback_all_metadata"),
            catalog=SZSE_ALL_FUND_CATALOG,
        )
        result: list[dict[str, Any]] = []
        categories: dict[str, dict[str, Any]] = {}
        for kind, catalog in SZSE_CATALOGS.items():
            first = self._szse_workbook_rows(
                self._fetch_szse_official_bytes(host="www.szse.cn", catalog=catalog,
                                                workbook=True, phase=f"{kind}_fallback_initial"), catalog=catalog,
            )
            count, category_date = self._szse_metadata(
                self._fetch_szse_official_bytes(host="www.szse.cn", catalog=catalog,
                                                workbook=False, phase=f"{kind}_fallback_metadata"), catalog=catalog,
            )
            second = self._szse_workbook_rows(
                self._fetch_szse_official_bytes(host="www.szse.cn", catalog=catalog,
                                                workbook=True, phase=f"{kind}_fallback_recheck"), catalog=catalog,
            )
            normalized = sorted((row["code"], row["name"]) for row in first)
            if len(first) != count or category_date != observed or normalized != sorted(
                (row["code"], row["name"]) for row in second
            ):
                raise FundCatalogConsistencyError(f"SZSE {kind} category fallback is incomplete or changed")
            result.extend({**row, "kind": kind} for row in first)
            categories[kind] = {"catalog_id": catalog, "record_count": count,
                                "normalized_sha256": hashlib.sha256(canonical_json(normalized).encode()).hexdigest()}
        if len(result) != total or len({row["code"] for row in result}) != total:
            raise FundCatalogConsistencyError("SZSE category fallback does not close the official all-Fund count")
        self.catalog_sessions = [{"route": "official_category_workbooks", "authority": "SZSE",
                                  "all_catalog_id": SZSE_ALL_FUND_CATALOG, "record_count": total,
                                  "as_of_date": observed, "categories": categories, "complete": True}]
        return result

    def _szse_listings_paginated(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        self.catalog_sessions: list[dict[str, Any]] = []
        for kind, catalog in SZSE_CATALOGS.items():
            last_error: Exception | None = None
            for catalog_attempt in range(1, SZSE_CATALOG_RESTART_ATTEMPTS + 1):
                try:
                    initial = self._fetch_szse_catalog_once(
                        kind=kind, catalog=catalog, phase=f"initial_attempt_{catalog_attempt}",
                    )
                    completion = self._fetch_szse_catalog_once(
                        kind=kind, catalog=catalog, phase=f"completion_recheck_{catalog_attempt}",
                    )
                    if (
                        initial["record_count"], initial["page_count"], initial["normalized_sha256"]
                    ) != (
                        completion["record_count"], completion["page_count"], completion["normalized_sha256"]
                    ):
                        raise FundCatalogConsistencyError(
                            f"SZSE_current_fund_list_{kind} changed during completion recheck"
                        )
                    self.catalog_sessions.append({
                        "kind": kind, "catalog_id": catalog,
                        "catalog_attempt": catalog_attempt,
                        "complete": True,
                        "duplicate_code_count": 0,
                        "initial": {key: initial[key] for key in ("record_count", "page_count", "page_numbers", "normalized_sha256")},
                        "completion_recheck": {key: completion[key] for key in ("record_count", "page_count", "page_numbers", "normalized_sha256")},
                    })
                    rows.extend(initial["rows"])
                    break
                except (FundSourceTransportError, FundCatalogConsistencyError) as exc:
                    last_error = exc
                    if catalog_attempt == SZSE_CATALOG_RESTART_ATTEMPTS:
                        raise
                    time.sleep(SZSE_CURL_RETRY_DELAY_SECONDS * catalog_attempt)
            else:
                if last_error:
                    raise last_error
        return rows

    def szse_lifecycle_for_code(self, code: str, fund_kind: str) -> dict[str, Any]:
        """Resolve one current SZSE listing through full official documents.

        Current-population membership and its structured Fund kind discover the
        object.  Listing dates come only from official SZSE lifecycle documents
        (or the bounded official-disclosure fallback owned by that contract).
        """
        source = SZSEFundLifecycleSource(
            self.root / "szse_lifecycle",
            timeout=self.timeout,
            session=self.session,
            receipts=self.calls,
        )
        try:
            return source.resolve_code(
                code,
                fund_kind=fund_kind,
                require_current_episode=True,
            )
        except SZSEFundLifecycleUnresolved as exc:
            raise FundIdentityReviewRequired(str(exc)) from exc
        except SZSEFundLifecycleError as exc:
            raise FundSourceContractError(str(exc)) from exc

    @staticmethod
    def _validate_szse_page(payload: Any, kind: str) -> None:
        route = f"SZSE_current_fund_list_{kind}"
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], Mapping):
            raise FundSourceContractError(f"{route} response is not the required page array")
        page = payload[0]
        metadata = page.get("metadata")
        if not isinstance(metadata, Mapping) or not {
            "pagecount", "recordcount", "pageno"
        }.issubset(metadata):
            raise FundSourceContractError(
                f"{route} response lacks pagination completeness metadata"
            )
        try:
            if (
                int(metadata["pagecount"]) < 1
                or int(metadata["recordcount"]) < 1
                or int(metadata["pageno"]) < 1
            ):
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise FundSourceContractError(f"{route} has invalid pagination metadata") from exc
        data = page.get("data")
        if not isinstance(data, list):
            raise FundSourceContractError(f"{route} response lacks required data list")
        if not all(isinstance(row, Mapping) and _szse_code(row) for row in data):
            raise FundSourceContractError(f"{route} contains a row without a Fund code")

    def tencent_kline(self, venue: str, code: str, count: int) -> list[list[str]]:
        symbol = ("sh" if venue == "SSE" else "sz") + code
        # Request native unadjusted exchange history. Adjustment is a Series
        # semantic and must never be silently introduced by the source route.
        params = {"param": f"{symbol},day,,,{count}", "_var": "kline_day"}
        started = time.monotonic(); response = None
        try:
            response = self.session.get(TENCENT_KLINE_URL, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=self.timeout)
            response.raise_for_status(); text = response.text
            payload = json.loads(text.split("=", 1)[1] if "=" in text else text)
            node = payload["data"][symbol]
            rows = node.get("day") or []
            self._record(route="Tencent_bounded_fund_kline", url=response.url, started=started, response=response)
            return rows
        except Exception as exc:
            self._record(route="Tencent_bounded_fund_kline", url=TENCENT_KLINE_URL, started=started, response=response, error=exc); raise

    def resolve_csrc_product_for_code(self, code: str) -> dict[str, Any]:
        """Bind a new exchange code to one regulator Fund and open its detail."""
        validate_url = f"{EID_BASE}/validate_fund.do"
        started = time.monotonic(); response = None
        try:
            response = self.session.post(
                validate_url, data={"cFundCode": code},
                headers={"User-Agent": "Mozilla/5.0 FR China Public Fund update"},
                timeout=self.timeout,
            )
            response.raise_for_status(); validation = response.json()
            if not validation.get("isSuccess") or validation.get("fundId") is None:
                raise FundIdentityReviewRequired(f"CSRC EID did not uniquely bind new Fund code {code}")
            self._record(route="CSRC_EID_validate_fund", url=validate_url, started=started, response=response)
            validation_digest = hashlib.sha256(response.content).hexdigest()
            self.calls[-1]["retained_response_file"] = self._retain_response(
                Path("csrc_eid") / f"validate_code_{code}_{validation_digest[:12]}.json",
                response.content,
            )
        except Exception as exc:
            self._record(route="CSRC_EID_validate_fund", url=validate_url, started=started, response=response, error=exc); raise
        fund_id = str(validation["fundId"])
        detail_url = f"{EID_BASE}/fund_detail.do?fundId={fund_id}"
        if self.cache_search_root is not None:
            cached = sorted(
                self.cache_search_root.glob(f"runs/*/source/fund_{fund_id}.html"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if cached:
                detail = parse_fund_detail_html(cached[0], csrc_eid_fund_id=fund_id)
                source_text = cached[0].read_text(encoding="utf-8")
                manager = re.search(r"advanced_search_comp\.html\?[^\"']*code=(\d+)", source_text)
                detail.update({
                    "manager_code": manager.group(1) if manager else None,
                    "exchange_code": code,
                    "source_document_sha256": sha256_file(cached[0]),
                    "source_document_bytes": cached[0].stat().st_size,
                })
                self.calls.append({
                    "route": "CSRC_EID_fund_detail", "url": detail_url,
                    "http_status": 200, "response_bytes": 0,
                    "response_sha256": detail["source_document_sha256"],
                    "elapsed_seconds": 0.0, "result": "reused_verified_cache",
                    "retained_response_file": str(cached[0]), "error": None,
                })
                return detail
        started = time.monotonic(); response = None
        try:
            response = self.session.get(detail_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=self.timeout)
            response.raise_for_status(); self._record(route="CSRC_EID_fund_detail", url=detail_url, started=started, response=response)
            detail_digest = hashlib.sha256(response.content).hexdigest()
            retained_detail = self._retain_response(
                Path("csrc_eid") / f"fund_{fund_id}_{detail_digest[:12]}.html",
                response.content,
            )
            self.calls[-1]["retained_response_file"] = retained_detail
            detail_path = self.root / retained_detail
            detail = parse_fund_detail_html(detail_path, csrc_eid_fund_id=fund_id)
            source_text = response.content.decode("utf-8", errors="replace")
            manager = re.search(r"advanced_search_comp\.html\?[^\"']*code=(\d+)", source_text)
            detail["manager_code"] = manager.group(1) if manager else None
            detail["exchange_code"] = code
            detail["source_document_sha256"] = sha256_file(detail_path)
            detail["source_document_bytes"] = detail_path.stat().st_size
            return detail
        except Exception as exc:
            self._record(route="CSRC_EID_fund_detail", url=detail_url, started=started, response=response, error=exc); raise


def load_update_context(repository: ValidatedUpdateRepository) -> FundUpdateContext:
    head = repository.current(UNIVERSE)
    if head is None:
        raise FundUpdateError("validated China Public Fund head is not initialized")
    root = resolve_unpublished_snapshot_path(head.snapshot_id)
    control = root / FUND_CONTROL
    if not control.is_file():
        raise FundUpdateError("validated Fund head lacks its snapshot-local control database")
    view = _fund_control_view(head.snapshot_id)
    watermarks = view.watermarks(ALL_METRICS)
    share_classes: dict[tuple[str, str], dict[str, str]] = {}
    listings: dict[tuple[str, str], dict[str, str]] = {}
    for row in view.aliases_matching(
        " WHERE subject_type='fund_share_class' AND alias_type='public_fund_code' AND acceptance_status='accepted'", ()
    ):
        scope = json.loads(row["scope_json"]); fid = str(scope.get("csrc_eid_fund_id") or "")
        if fid and row["effective_end"] is None:
            share_classes[(fid, str(row["alias_value"]).zfill(6))] = {"subject_id": row["subject_id"], "identity_decision_id": _identity_decision_view(view, "fund_share_class", row["subject_id"])}
    for row in view.aliases_matching(
        " WHERE subject_type='listing' AND alias_type='listing_code' AND acceptance_status='accepted' AND effective_end IS NULL", ()
    ):
        scope = json.loads(row["scope_json"]); venue = str(scope.get("venue") or "").upper()
        listings[(venue, str(row["alias_value"]).zfill(6))] = {"subject_id": row["subject_id"], "identity_decision_id": _identity_decision_view(view, "listing", row["subject_id"]), "csrc_eid_fund_id": str(scope.get("csrc_eid_fund_id") or "")}
    return FundUpdateContext(head, root, control, watermarks, share_classes, listings, _series_map_view(view))


def _identity_decision_view(view: IncrementalControlView, subject_type: str, subject_id: str) -> str:
    row = view.subject(subject_type, subject_id)
    if row is None:
        raise FundUpdateError(f"alias references absent subject: {subject_type} {subject_id}")
    decision = json.loads(row["attributes_json"]).get("identity_decision_id")
    if not decision:
        raise FundUpdateError(f"subject lacks durable identity decision: {subject_type} {subject_id}")
    return str(decision)


def _series_map_view(view: IncrementalControlView) -> dict[tuple[str, str, str], str]:
    result: dict[tuple[str, str, str], str] = {}
    series_subjects = {str(row["subject_id"]): row for row in view.subjects("series")}
    for row in view.relationships_matching(
        " WHERE relationship_type='series_of' AND from_type='series'"
    ):
        subject = series_subjects.get(str(row["from_id"]))
        metric = json.loads(subject["attributes_json"]).get("metric_id") if subject else None
        if metric:
            result[(str(row["to_type"]), str(row["to_id"]), str(metric))] = str(row["from_id"])
    return result


def _unique_existing_entity(view: IncrementalControlView, *, alias_type: str, alias_value: str) -> str | None:
    if not alias_value:
        return None
    rows = view.aliases_matching(
        " WHERE subject_type='entity' AND alias_type=? AND alias_value=? AND acceptance_status='accepted' AND effective_end IS NULL",
        (alias_type, alias_value),
    )
    values = {str(row["subject_id"]) for row in rows}
    if len(values) > 1:
        raise FundIdentityReviewRequired(f"new Fund evidence ambiguously matches entity alias {alias_type}:{alias_value}")
    return next(iter(values)) if values else None


def onboard_new_exchange_listings(
    context: FundUpdateContext,
    source: PublicFundSourceClient,
    sse_rows: Sequence[Mapping[str, Any]],
    szse_rows: Sequence[Mapping[str, Any]],
    new_listings: Sequence[tuple[str, str]],
) -> tuple[FundUpdateContext, Path | None]:
    """Accept regulator-bound new Fund objects into the current generation.

    This bounded route is intentionally strict: an exchange code must bind to
    one CSRC EID Fund and an opened regulator detail record.  SSE listing dates
    remain sourced from its structured official list.  SZSE listing dates must
    first resolve through the production official lifecycle contract. Existing
    economic subjects are resolved before allocation; codes and names are then
    recorded only as aliases/provenance.
    """
    if not new_listings:
        return context, None
    if any(venue not in {"SSE", "SZSE"} for venue, _ in new_listings):
        raise FundIdentityReviewRequired("new Fund listing uses an unsupported exchange lifecycle route")
    sse_by_code = {str(row.get("FUND_CODE") or "").zfill(6): dict(row) for row in sse_rows}
    szse_by_code = {str(row.get("code") or "").zfill(6): dict(row) for row in szse_rows}
    resolved_exchange: dict[tuple[str, str], dict[str, Any]] = {}
    for venue, code in new_listings:
        if venue == "SSE":
            row = sse_by_code.get(code)
            listing_date = str((row or {}).get("LISTING_DATE") or "")[:10]
            if row is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", listing_date):
                raise FundIdentityReviewRequired(f"SSE {code} lacks an authoritative listing date")
            resolved_exchange[(venue, code)] = {
                "row": row,
                "listing_date": listing_date,
                "display_name": row.get("FUND_EXPANSION_ABBR") or row.get("FUND_ABBR"),
                "product_structure_code": row.get("CATEGORY"),
                "lifecycle_evidence": [],
                "provenance_refs": ["SSE_current_fund_list"],
            }
            continue
        row = szse_by_code.get(code)
        if row is None or row.get("kind") not in {"etf", "lof", "public_reit"}:
            raise FundIdentityReviewRequired(f"SZSE {code} lacks a supported structured Fund classification")
        resolution = source.szse_lifecycle_for_code(code, str(row["kind"]))
        open_episodes = [
            dict(episode) for episode in resolution.get("episodes", [])
            if episode.get("listing_end_date") is None
        ]
        if len(open_episodes) != 1 or open_episodes[0].get("fund_kind") != row["kind"]:
            raise FundIdentityReviewRequired(f"SZSE {code} lifecycle does not bind one matching current episode")
        episode = open_episodes[0]
        start_evidence = [dict(item) for item in episode.get("start_evidence", [])]
        if not start_evidence:
            raise FundIdentityReviewRequired(f"SZSE {code} current episode lacks retained start evidence")
        resolved_exchange[(venue, code)] = {
            "row": row,
            "listing_date": episode["listing_start_date"],
            "display_name": row.get("name"),
            "product_structure_code": row.get("kind"),
            "lifecycle_evidence": [episode],
            "provenance_refs": [
                "SZSE_current_fund_list",
                *[str(item["document_url"]) for item in start_evidence],
            ],
        }
    identity = InstallationIdentityState(resolve_identity_state_path(), resolve_identity_state_backup_root())
    backup = identity.backup()
    subjects = list(context.new_subjects); aliases = list(context.new_aliases)
    relationships = list(context.new_relationships); changes = list(context.identity_changes)
    share_bindings = dict(context.share_class_bindings); listing_bindings = dict(context.listing_bindings)
    series_bindings = dict(context.series_bindings)
    now = utc_now()
    for venue, code in new_listings:
        exchange = resolved_exchange[(venue, code)]
        exchange_row = exchange["row"]
        listing_date = str(exchange["listing_date"])
        detail = source.resolve_csrc_product_for_code(code)
        fund_id = str(detail["csrc_eid_fund_id"])
        provenance = [detail["source_url"], *exchange["provenance_refs"]]
        fund_scope = {"jurisdiction": "CN", "object_role": "fund_product"}
        share_scope = {"csrc_eid_fund_id": fund_id, "jurisdiction": "CN", "object_role": "fund_share_class"}
        try:
            fund_decision = identity.resolve_accepted_identity([{"authority": "CSRC_EID", "identifier_type": "public_fund_id", "identifier_value": fund_id, "scope": fund_scope}])
            new_fund = False
        except KeyError:
            fund_decision = identity.create_decision(subject_type="fund", accepted_identity_statement=f"China public Fund product uniquely registered by CSRC EID Fund ID {fund_id}", economic_object_type="china_public_fund_product", provenance_refs=provenance, decision_attributes={"jurisdiction": "CN", "offering_status": "Public Fund"})
            identity.register_accepted_crosswalk(identity_decision_id=fund_decision["identity_decision_id"], subject_type="fund", subject_id=fund_decision["subject_id"], authority="CSRC_EID", identifier_type="public_fund_id", identifier_value=fund_id, scope=fund_scope, effective_start=detail.get("contract_effective_date"), effective_end=detail.get("contract_end_date"), provenance_refs=provenance)
            new_fund = True
        try:
            share_decision = identity.resolve_accepted_identity([{"authority": "CSRC_EID", "identifier_type": "public_fund_code", "identifier_value": code, "scope": share_scope}])
            new_share = False
        except KeyError:
            share_decision = identity.create_decision(subject_type="fund_share_class", accepted_identity_statement=f"Share class {code} of CSRC EID Fund {fund_id}", economic_object_type="china_public_fund_share_class", provenance_refs=provenance, decision_attributes={"fund_subject_id": fund_decision["subject_id"]})
            identity.register_accepted_crosswalk(identity_decision_id=share_decision["identity_decision_id"], subject_type="fund_share_class", subject_id=share_decision["subject_id"], authority="CSRC_EID", identifier_type="public_fund_code", identifier_value=code, scope=share_scope, provenance_refs=provenance)
            new_share = True
        decisions = identity.create_decisions_batch([
            {"subject_type": "instrument", "accepted_identity_statement": f"{venue} tradable Fund security representing CSRC EID Fund {fund_id} share class {code}", "economic_object_type": "china_exchange_tradable_fund_instrument", "provenance_refs": provenance},
            {"subject_type": "listing", "accepted_identity_statement": f"{venue} listing episode for Fund security {code} beginning {listing_date}", "economic_object_type": "china_exchange_fund_listing_or_counter", "provenance_refs": provenance},
            *[{"subject_type": "series", "accepted_identity_statement": f"Canonical {metric} Series for new China Public Fund object {fund_id}/{code}", "economic_object_type": "canonical_metric_series", "provenance_refs": provenance, "decision_attributes": {"metric_id": metric}} for metric in NAV_METRICS + LISTED_METRICS],
        ])
        instrument, listing, *series_decisions = decisions
        identity.register_accepted_crosswalk(identity_decision_id=instrument["identity_decision_id"], subject_type="instrument", subject_id=instrument["subject_id"], authority=venue, identifier_type="fund_security_code", identifier_value=code, scope={"csrc_eid_fund_id": fund_id, "jurisdiction": "CN", "object_role": "tradable_fund_instrument", "venue": venue}, effective_start=listing_date, provenance_refs=provenance)
        identity.register_accepted_crosswalk(identity_decision_id=listing["identity_decision_id"], subject_type="listing", subject_id=listing["subject_id"], authority=venue, identifier_type="listing_code", identifier_value=code, scope={"csrc_eid_fund_id": fund_id, "jurisdiction": "CN", "object_role": "exchange_listing", "venue": venue}, effective_start=listing_date, provenance_refs=provenance)

        def subject(decision: Mapping[str, Any], domain: str, name: str | None, start: str | None, venue_value: str | None = None, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
            attrs = {"display_name": name, "economic_object_type": decision["economic_object_type"], "identity_contract": "installation_local_standard_id_ready", "identity_decision_id": decision["identity_decision_id"], "jurisdiction": "CN", "universe": "Fund", **dict(extra or {})}
            return {"subject_type": decision["subject_type"], "subject_id": decision["subject_id"], "domain": domain, "legacy_alias": None, "market": "CN", "venue": venue_value, "effective_start": start, "effective_end": None, "code_aliases_json": "[]", "attributes_json": canonical_json(attrs), "resolution_status": "accepted_canonical_unpublished", "updated_at_utc": now}
        if new_fund:
            subjects.append(subject(fund_decision, "funds_etfs", detail.get("fund_name"), detail.get("contract_effective_date"), extra={"csrc_eid_fund_id": fund_id, "operation_type": detail.get("operation_type"), "fund_type": detail.get("fund_type")}))
            aliases.extend([
                canonical_alias_record(subject_type="fund", subject_id=fund_decision["subject_id"], alias_type="public_fund_id", alias_value=fund_id, scope=fund_scope, effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now),
                canonical_alias_record(subject_type="fund", subject_id=fund_decision["subject_id"], alias_type="documented_name", alias_value=detail["fund_name"], scope={"jurisdiction": "CN", "object_role": "fund_product"}, effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now),
            ])
        if new_share:
            subjects.append(subject(share_decision, "funds_etfs", detail.get("fund_name"), detail.get("contract_effective_date"), extra={"csrc_eid_fund_id": fund_id}))
            aliases.extend([
                canonical_alias_record(subject_type="fund_share_class", subject_id=share_decision["subject_id"], alias_type="public_fund_code", alias_value=code, scope=share_scope, effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now),
                canonical_alias_record(subject_type="fund_share_class", subject_id=share_decision["subject_id"], alias_type="documented_name", alias_value=detail["fund_name"], scope={"jurisdiction": "CN", "object_role": "fund_share_class", "csrc_eid_fund_id": fund_id}, effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now),
            ])
            relationships.append(canonical_relationship_record(from_type="fund_share_class", from_id=share_decision["subject_id"], to_type="fund", to_id=fund_decision["subject_id"], relationship_type="share_class_of", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#share_class_of", effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now))
        subjects.extend([
            subject(instrument, "funds_etfs", exchange["display_name"], listing_date, venue_value=venue),
            subject(listing, "funds_etfs", exchange["display_name"], listing_date, venue_value=venue, extra={"listing_start_date": listing_date}),
        ])
        aliases.extend([
            canonical_alias_record(subject_type="instrument", subject_id=instrument["subject_id"], alias_type="fund_security_code", alias_value=code, scope={"csrc_eid_fund_id": fund_id, "jurisdiction": "CN", "object_role": "tradable_fund_instrument", "venue": venue}, effective_start=listing_date, effective_end=None, provenance_refs=provenance, updated_at_utc=now),
            canonical_alias_record(subject_type="listing", subject_id=listing["subject_id"], alias_type="listing_code", alias_value=code, scope={"csrc_eid_fund_id": fund_id, "object_role": "exchange_listing", "venue": venue}, effective_start=listing_date, effective_end=None, provenance_refs=provenance, updated_at_utc=now),
        ])
        relationships.extend([
            canonical_relationship_record(from_type="instrument", from_id=instrument["subject_id"], to_type="fund_share_class", to_id=share_decision["subject_id"], relationship_type="represents_share_class", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#represents_share_class", effective_start=listing_date, effective_end=None, provenance_refs=provenance, updated_at_utc=now),
            canonical_relationship_record(from_type="listing", from_id=listing["subject_id"], to_type="instrument", to_id=instrument["subject_id"], relationship_type="listed_as", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#listed_as", effective_start=listing_date, effective_end=None, provenance_refs=provenance, updated_at_utc=now),
        ])
        targets = [("fund_share_class", share_decision["subject_id"], metric) for metric in NAV_METRICS] + [("listing", listing["subject_id"], metric) for metric in LISTED_METRICS]
        for decision, (target_type, target_id, metric) in zip(series_decisions, targets):
            subjects.append(subject(decision, "funds_etfs", f"{metric} Series", None, extra={"metric_id": metric, "series_dimensions": {}}))
            relationships.append(canonical_relationship_record(from_type="series", from_id=decision["subject_id"], to_type=target_type, to_id=target_id, relationship_type="series_of", definition_ref="FR_DATA_GUARDRAILS#series_of", effective_start=None, effective_end=None, provenance_refs=provenance, attributes={"metric_id": metric, "series_dimensions": {}}, updated_at_utc=now))
            series_bindings[(target_type, target_id, metric)] = decision["subject_id"]
        view = _fund_control_view(context.head.snapshot_id)
        manager_id = _unique_existing_entity(view, alias_type="public_fund_manager_code", alias_value=str(detail.get("manager_code") or ""))
        custodian_id = _unique_existing_entity(view, alias_type="documented_name", alias_value=str(detail.get("custodian_name") or ""))
        if manager_id:
            relationships.append(canonical_relationship_record(from_type="fund", from_id=fund_decision["subject_id"], to_type="entity", to_id=manager_id, relationship_type="managed_by", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#managed_by", effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now))
        if custodian_id:
            relationships.append(canonical_relationship_record(from_type="fund", from_id=fund_decision["subject_id"], to_type="entity", to_id=custodian_id, relationship_type="custodied_by", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#custodied_by", effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now))
        share_bindings[(fund_id, code)] = {"subject_id": share_decision["subject_id"], "identity_decision_id": share_decision["identity_decision_id"]}
        listing_bindings[(venue, code)] = {"subject_id": listing["subject_id"], "identity_decision_id": listing["identity_decision_id"], "csrc_eid_fund_id": fund_id}
        changes.append({
            "change_type": "new_exchange_listed_fund_object_graph",
            "venue": venue,
            "code": code,
            "csrc_eid_fund_id": fund_id,
            "fund_name": detail.get("fund_name"),
            "manager_name": detail.get("manager_name"),
            "manager_code": detail.get("manager_code"),
            "custodian_name": detail.get("custodian_name"),
            "product_structure_code": exchange["product_structure_code"],
            "fund_id": fund_decision["subject_id"],
            "share_class_id": share_decision["subject_id"],
            "instrument_id": instrument["subject_id"],
            "listing_id": listing["subject_id"],
            "listing_start_date": listing_date,
            "contract_effective_date": detail.get("contract_effective_date"),
            "source_document_url": detail.get("source_url"),
            "source_document_sha256": detail.get("source_document_sha256"),
            "source_document_bytes": detail.get("source_document_bytes"),
            "exchange_lifecycle_evidence": exchange["lifecycle_evidence"],
            "identity_decisions_created": len(decisions) + int(new_fund) + int(new_share),
        })
    return replace(context, share_class_bindings=share_bindings, listing_bindings=listing_bindings, series_bindings=series_bindings, new_subjects=tuple(subjects), new_aliases=tuple(aliases), new_relationships=tuple(relationships), identity_changes=tuple(changes)), backup


def ensure_incremental_series(
    context: FundUpdateContext,
    targets: Iterable[tuple[str, str, str]],
    *,
    existing_backup: Path | None,
) -> tuple[FundUpdateContext, Path | None]:
    missing = sorted(set(targets) - set(context.series_bindings))
    if not missing:
        return context, existing_backup
    identity = InstallationIdentityState(resolve_identity_state_path(), resolve_identity_state_backup_root())
    backup = existing_backup or identity.backup()
    decisions = identity.create_decisions_batch([
        {
            "subject_type": "series",
            "accepted_identity_statement": f"Canonical {metric} Series for accepted {subject_type} {subject_id}",
            "economic_object_type": "canonical_metric_series",
            "provenance_refs": ["current user-triggered source observation", "config/metrics_registry.json"],
            "decision_attributes": {"metric_id": metric, "subject_type": subject_type, "subject_id": subject_id},
        }
        for subject_type, subject_id, metric in missing
    ])
    now = utc_now(); subjects = list(context.new_subjects); relationships = list(context.new_relationships)
    bindings = dict(context.series_bindings); changes = list(context.identity_changes)
    for decision, (subject_type, subject_id, metric) in zip(decisions, missing):
        attrs = {"display_name": f"{metric} Series", "economic_object_type": "canonical_metric_series", "identity_contract": "installation_local_standard_id_ready", "identity_decision_id": decision["identity_decision_id"], "jurisdiction": "CN", "universe": "Fund", "metric_id": metric, "series_dimensions": {}}
        subjects.append({"subject_type": "series", "subject_id": decision["subject_id"], "domain": "funds_etfs", "legacy_alias": None, "market": "CN", "venue": None, "effective_start": None, "effective_end": None, "code_aliases_json": "[]", "attributes_json": canonical_json(attrs), "resolution_status": "accepted_canonical_unpublished", "updated_at_utc": now})
        relationships.append(canonical_relationship_record(from_type="series", from_id=decision["subject_id"], to_type=subject_type, to_id=subject_id, relationship_type="series_of", definition_ref="FR_DATA_GUARDRAILS#series_of", effective_start=None, effective_end=None, provenance_refs=["current user-triggered source observation", "config/metrics_registry.json"], attributes={"metric_id": metric, "series_dimensions": {}}, updated_at_utc=now))
        bindings[(subject_type, subject_id, metric)] = decision["subject_id"]
        changes.append({"change_type": "new_series_for_existing_subject", "subject_type": subject_type, "subject_id": subject_id, "metric_id": metric, "series_id": decision["subject_id"], "identity_decisions_created": 1})
    return replace(context, series_bindings=bindings, new_subjects=tuple(subjects), new_relationships=tuple(relationships), identity_changes=tuple(changes)), backup


def onboard_new_csrc_share_classes(
    context: FundUpdateContext,
    source: PublicFundSourceClient,
    valuation_rows: Sequence[Mapping[str, Any]],
    *,
    existing_backup: Path | None,
) -> tuple[FundUpdateContext, Path | None, set[tuple[str, str]]]:
    """Onboard regulator-observed Fund/share-class objects before facts.

    A CSRC EID Fund ID plus its scoped public-fund code is accepted identity
    evidence for the share class, but not a lifecycle-start date. New Fund
    products additionally require their opened regulator detail record.
    """
    representatives: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in valuation_rows:
        fund_id = str((row.get("fund") or {}).get("idStr") or "")
        code = str(row.get("code") or "").zfill(6)
        if fund_id and code and (fund_id, code) not in context.share_class_bindings:
            representatives.setdefault((fund_id, code), row)
    if not representatives:
        return context, existing_backup, set()

    identity = InstallationIdentityState(resolve_identity_state_path(), resolve_identity_state_backup_root())
    backup = existing_backup or identity.backup()
    subjects = list(context.new_subjects); aliases = list(context.new_aliases)
    relationships = list(context.new_relationships); changes = list(context.identity_changes)
    share_bindings = dict(context.share_class_bindings); series_bindings = dict(context.series_bindings)
    now = utc_now()
    fund_bindings: dict[str, dict[str, str]] = {}
    view = _fund_control_view(context.head.snapshot_id)
    for row in view.aliases_matching(
        " WHERE subject_type='fund' AND alias_type='public_fund_id' AND acceptance_status='accepted' AND effective_end IS NULL", ()
    ):
        fund_bindings[str(row["alias_value"])] = {
            "subject_id": str(row["subject_id"]),
            "identity_decision_id": _identity_decision_view(view, "fund", str(row["subject_id"])),
        }

    def subject(
        decision: Mapping[str, Any],
        name: str | None,
        effective_start: str | None,
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        attrs = {
            "display_name": name,
            "economic_object_type": decision["economic_object_type"],
            "identity_contract": "installation_local_standard_id_ready",
            "identity_decision_id": decision["identity_decision_id"],
            "jurisdiction": "CN", "universe": "Fund", **dict(extra or {}),
        }
        return {
            "subject_type": decision["subject_type"], "subject_id": decision["subject_id"],
            "domain": "funds_etfs", "legacy_alias": None, "market": "CN", "venue": None,
            "effective_start": effective_start, "effective_end": None, "code_aliases_json": "[]",
            "attributes_json": canonical_json(attrs),
            "resolution_status": "accepted_canonical_unpublished", "updated_at_utc": now,
        }

    new_fund_ids = sorted({fund_id for fund_id, _code in representatives if fund_id not in fund_bindings})
    for fund_id in new_fund_ids:
        code = next(code for candidate_fund, code in representatives if candidate_fund == fund_id)
        detail = source.resolve_csrc_product_for_code(code)
        if str(detail["csrc_eid_fund_id"]) != fund_id:
            raise FundIdentityReviewRequired(
                f"CSRC valuation/detail Fund identity mismatch for {fund_id}/{code}"
            )
        provenance = [detail["source_url"], "CSRC_EID_current_valuation"]
        decision = identity.create_decision(
            subject_type="fund",
            accepted_identity_statement=f"China public Fund product registered by CSRC EID Fund ID {fund_id}",
            economic_object_type="china_public_fund_product",
            provenance_refs=provenance,
            decision_attributes={"jurisdiction": "CN", "offering_status": "Public Fund"},
        )
        scope = {"jurisdiction": "CN", "object_role": "fund_product"}
        identity.register_accepted_crosswalk(
            identity_decision_id=decision["identity_decision_id"], subject_type="fund",
            subject_id=decision["subject_id"], authority="CSRC_EID",
            identifier_type="public_fund_id", identifier_value=fund_id, scope=scope,
            effective_start=detail.get("contract_effective_date"),
            effective_end=detail.get("contract_end_date"), provenance_refs=provenance,
            validate_after_registration=False,
        )
        subjects.append(subject(
            decision, detail.get("fund_name"), detail.get("contract_effective_date"),
            {"csrc_eid_fund_id": fund_id, "operation_type": detail.get("operation_type"), "fund_type": detail.get("fund_type")},
        ))
        aliases.extend([
            canonical_alias_record(subject_type="fund", subject_id=decision["subject_id"], alias_type="public_fund_id", alias_value=fund_id, scope=scope, effective_start=detail.get("contract_effective_date"), effective_end=detail.get("contract_end_date"), provenance_refs=provenance, updated_at_utc=now),
            canonical_alias_record(subject_type="fund", subject_id=decision["subject_id"], alias_type="documented_name", alias_value=detail["fund_name"], scope=scope, effective_start=detail.get("contract_effective_date"), effective_end=detail.get("contract_end_date"), provenance_refs=provenance, updated_at_utc=now),
        ])
        manager_id = _unique_existing_entity(view, alias_type="public_fund_manager_code", alias_value=str(detail.get("manager_code") or ""))
        custodian_id = _unique_existing_entity(view, alias_type="documented_name", alias_value=str(detail.get("custodian_name") or ""))
        if manager_id:
            relationships.append(canonical_relationship_record(from_type="fund", from_id=decision["subject_id"], to_type="entity", to_id=manager_id, relationship_type="managed_by", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#managed_by", effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now))
        if custodian_id:
            relationships.append(canonical_relationship_record(from_type="fund", from_id=decision["subject_id"], to_type="entity", to_id=custodian_id, relationship_type="custodied_by", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#custodied_by", effective_start=detail.get("contract_effective_date"), effective_end=None, provenance_refs=provenance, updated_at_utc=now))
        fund_bindings[fund_id] = {"subject_id": decision["subject_id"], "identity_decision_id": decision["identity_decision_id"]}
        changes.append({
            "change_type": "new_public_fund_product", "csrc_eid_fund_id": fund_id,
            "fund_id": decision["subject_id"], "fund_name": detail.get("fund_name"),
            "contract_effective_date": detail.get("contract_effective_date"),
            "source_document_url": detail.get("source_url"),
            "source_document_sha256": detail.get("source_document_sha256"),
            "identity_decisions_created": 1,
        })

    share_decisions = identity.create_decisions_batch([
        {
            "subject_type": "fund_share_class",
            "accepted_identity_statement": f"CSRC EID public Fund share class {code} under Fund ID {fund_id}",
            "economic_object_type": "china_public_fund_share_class",
            "provenance_refs": ["CSRC_EID_current_valuation"],
            "decision_attributes": {"fund_subject_id": fund_bindings[fund_id]["subject_id"]},
        }
        for fund_id, code in sorted(representatives)
    ])
    series_decisions = identity.create_decisions_batch([
        {
            "subject_type": "series",
            "accepted_identity_statement": f"Canonical {metric} Series for CSRC EID Fund share class {fund_id}/{code}",
            "economic_object_type": "canonical_metric_series",
            "provenance_refs": ["CSRC_EID_current_valuation", "config/metrics_registry.json"],
            "decision_attributes": {"metric_id": metric},
        }
        for fund_id, code in sorted(representatives)
        for metric in NAV_METRICS
    ])
    series_iter = iter(series_decisions)
    ordered_representatives = sorted(representatives)
    for index, (decision, (fund_id, code)) in enumerate(zip(share_decisions, ordered_representatives)):
        raw = representatives[(fund_id, code)]
        name = str(raw.get("shortName") or "") or None
        provenance = ["CSRC_EID_current_valuation", f"csrc_eid_fund_id={fund_id}"]
        scope = {"csrc_eid_fund_id": fund_id, "jurisdiction": "CN", "object_role": "fund_share_class"}
        identity.register_accepted_crosswalk(
            identity_decision_id=decision["identity_decision_id"], subject_type="fund_share_class",
            subject_id=decision["subject_id"], authority="CSRC_EID",
            identifier_type="public_fund_code", identifier_value=code, scope=scope,
            provenance_refs=provenance,
            validate_after_registration=index == len(ordered_representatives) - 1,
        )
        subjects.append(subject(decision, name, None, {"csrc_eid_fund_id": fund_id}))
        aliases.append(canonical_alias_record(subject_type="fund_share_class", subject_id=decision["subject_id"], alias_type="public_fund_code", alias_value=code, scope=scope, effective_start=None, effective_end=None, provenance_refs=provenance, updated_at_utc=now))
        if name:
            aliases.append(canonical_alias_record(subject_type="fund_share_class", subject_id=decision["subject_id"], alias_type="documented_name", alias_value=name, scope=scope, effective_start=None, effective_end=None, provenance_refs=provenance, updated_at_utc=now))
        relationships.append(canonical_relationship_record(from_type="fund_share_class", from_id=decision["subject_id"], to_type="fund", to_id=fund_bindings[fund_id]["subject_id"], relationship_type="share_class_of", definition_ref="FR_CHINA_PUBLIC_FUND_FOUNDATION#share_class_of", effective_start=None, effective_end=None, provenance_refs=provenance, updated_at_utc=now))
        share_bindings[(fund_id, code)] = {"subject_id": decision["subject_id"], "identity_decision_id": decision["identity_decision_id"]}
        for metric in NAV_METRICS:
            series_decision = next(series_iter)
            subjects.append(subject(series_decision, f"{metric} Series", None, {"metric_id": metric, "series_dimensions": {}}))
            relationships.append(canonical_relationship_record(from_type="series", from_id=series_decision["subject_id"], to_type="fund_share_class", to_id=decision["subject_id"], relationship_type="series_of", definition_ref="FR_DATA_GUARDRAILS#series_of", effective_start=None, effective_end=None, provenance_refs=provenance, attributes={"metric_id": metric, "series_dimensions": {}}, updated_at_utc=now))
            series_bindings[("fund_share_class", decision["subject_id"], metric)] = series_decision["subject_id"]
        changes.append({
            "change_type": "new_fund_share_class", "csrc_eid_fund_id": fund_id,
            "code": code, "share_class_id": decision["subject_id"], "share_class_name": name,
            "effective_start": None,
            "authoritative_observation_date": raw.get("valuationDate") or raw.get("reportSendDate"),
            "authoritative_record_sha256": hashlib.sha256(canonical_json(raw).encode()).hexdigest(),
            "lifecycle_start_inferred_from_observation": False,
            "identity_decisions_created": 3,
        })
    return replace(
        context, share_class_bindings=share_bindings, series_bindings=series_bindings,
        new_subjects=tuple(subjects), new_aliases=tuple(aliases),
        new_relationships=tuple(relationships), identity_changes=tuple(changes),
    ), backup, set(representatives)


def _source_input(*, provider: str, route: str, symbol: str, field: str, value: Any, metric: str, day: str, unit: str, currency: str, scale: str, receipt: str, source_version_scope: str | None = None, source_detail: Mapping[str, Any] | None = None, time_role: str = "observation_date") -> dict[str, Any]:
    return {
        "metric_id": metric, "observation_date": day, "time_role": time_role,
        "native_value": value, "fact_value": value, "native_field": field,
        "provider_native_symbol": symbol, "actual_upstream_owner": provider,
        "exact_callable_or_route": route, "native_unit": unit, "canonical_unit": unit,
        "native_currency": currency, "canonical_currency": currency,
        "native_scale": scale, "canonical_scale": scale, "canonical_unit_type": unit,
        "direct_or_derived": "direct", "semantic_basis": f"direct published observation from {provider}",
        "source_version_scope": source_version_scope or day, "fact_version_scope": day,
        "response_content_hash": receipt, "lineage": {"receipt": receipt, **dict(source_detail or {})},
    }


def build_incremental_rows(context: FundUpdateContext, valuation_rows: Sequence[Mapping[str, Any]], market_rows: Mapping[tuple[str, str], Sequence[Sequence[str]]], *, processed_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    series = context.series_bindings
    sources: dict[str, dict[str, Any]] = {}; facts: dict[str, dict[str, Any]] = {}
    skipped_unknown: set[tuple[str, str]] = set(); skipped_empty = 0; conflicts: list[dict[str, Any]] = []
    conflicted_fact_keys: set[str] = set()

    def accept(raw: dict[str, Any], target: FundTarget, series_id: str) -> None:
        source = canonical_source_row(raw, target=target, series_id=series_id, processed_at_utc=processed_at)
        fact = canonical_fact_row(raw, target=target, series_id=series_id, canonical_source_key=source["source_observation_key"])
        prior = facts.get(fact["logical_fact_key"])
        if prior and prior["normalized_value"] != fact["normalized_value"]:
            conflicts.append({"logical_fact_key": fact["logical_fact_key"], "subject_id": target.subject_id, "metric_id": raw["metric_id"], "economic_date": raw["observation_date"], "values": sorted({prior["normalized_value"], fact["normalized_value"]})})
            facts.pop(fact["logical_fact_key"], None); conflicted_fact_keys.add(fact["logical_fact_key"])
        sources[source["source_observation_key"]] = source
        if fact["logical_fact_key"] not in conflicted_fact_keys:
            facts[fact["logical_fact_key"]] = fact

    for item in valuation_rows:
        fund = item.get("fund") or {}; fid = str(fund.get("idStr") or ""); code = str(item.get("code") or "").zfill(6)
        binding = context.share_class_bindings.get((fid, code))
        if not binding:
            skipped_unknown.add((fid, code)); continue
        target = FundTarget(
            route="CSRC_EID_current_valuation", code=code,
            subject_type="fund_share_class", subject_id=binding["subject_id"],
            identity_decision_id=binding["identity_decision_id"],
            fund_subject_id="", csrc_eid_fund_id=fid,
            effective_start=None, effective_end=None,
            evidence_refs=("CSRC_EID_current_valuation",),
            mapping_basis="accepted CSRC EID fundId plus scoped share-class code",
        )
        day = str(item.get("valuationDate") or item.get("reportSendDate") or "")[:10]
        receipt = hashlib.sha256(canonical_json(item).encode()).hexdigest()
        for metric, field in (("fund.nav", "shareNetValue"), ("fund.accumulated_nav", "totalNetValue")):
            value = item.get(field)
            if value in (None, ""):
                skipped_empty += 1; continue
            if day <= context.watermarks.get(("fund_share_class", target.subject_id, metric), "0000-00-00"):
                continue
            series_id = series.get(("fund_share_class", target.subject_id, metric))
            if not series_id:
                raise FundUpdateError(f"accepted share class lacks canonical Series for {metric}: {target.subject_id}")
            classification = str((item.get("classification") or {}).get("code") or "")
            record_id = str(item.get("idStr") or receipt)
            accept(_source_input(provider="CSRC_EID", route="getPublicFundJZInfoMore.do", symbol=code, field=field, value=value, metric=metric, day=day, unit="currency_per_fund_unit", currency="CNY", scale="1", receipt=receipt, source_version_scope=f"{day}|record={record_id}|classification={classification}", source_detail={"csrc_eid_record_id": record_id, "classification_code": classification, "economic_date_field": "valuationDate" if item.get("valuationDate") else "reportSendDate"}, time_role="nav_date" if item.get("valuationDate") else "observation_date"), target, series_id)

    for (venue, code), rows in market_rows.items():
        binding = context.listing_bindings[(venue, code)]
        target = FundTarget(
            route="Tencent_bounded_fund_kline", code=code,
            subject_type="listing", subject_id=binding["subject_id"],
            identity_decision_id=binding["identity_decision_id"],
            fund_subject_id="", csrc_eid_fund_id=binding["csrc_eid_fund_id"],
            effective_start=None, effective_end=None,
            evidence_refs=(f"{venue}_current_listing", "Tencent_bounded_fund_kline"),
            mapping_basis="accepted effective-dated exchange listing alias",
        )
        for values in rows:
            if len(values) < 7: continue
            day = str(values[0])[:10]
            for metric, field, index, multiplier, unit, currency in (
                ("market.close_price", "close", 2, 1, "currency_per_fund_unit", "CNY"),
                ("market.volume", "volume_lots", 5, 100, "shares", ""),
                ("market.trade_amount", "amount_ten_thousand_cny", 6, 10000, "currency", "CNY"),
            ):
                if day <= context.watermarks.get(("listing", target.subject_id, metric), "0000-00-00"):
                    continue
                value = str(float(values[index]) * multiplier) if multiplier != 1 else str(values[index])
                sid = series.get(("listing", target.subject_id, metric))
                if not sid: raise FundUpdateError(f"accepted listing lacks canonical Series for {metric}: {target.subject_id}")
                receipt = hashlib.sha256(canonical_json(list(values)).encode()).hexdigest()
                accept(_source_input(provider="Tencent", route="newfqkline/get", symbol=("sh" if venue == "SSE" else "sz") + code, field=field, value=value, metric=metric, day=day, unit=unit, currency=currency, scale="1", receipt=receipt), target, sid)
    return list(sources.values()), list(facts.values()), {"unknown_share_class_pairs": sorted(skipped_unknown), "unknown_share_class_pair_count": len(skipped_unknown), "empty_metric_values": skipped_empty, "conflicting_logical_fact_count": len(conflicted_fact_keys), "conflict_examples": conflicts[:20]}


def _write_parquet_groups(root: Path, layer: str, rows: Sequence[Mapping[str, Any]], run_id: str, created_at: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []; locatable: list[dict[str, Any]] = []
    by_metric: dict[str, list[dict[str, Any]]] = {}
    for row in rows: by_metric.setdefault(str(row["metric_id"]), []).append(dict(row))
    for metric, group in sorted(by_metric.items()):
        metric_path = metric.replace(".", "_")
        path = root / layer / "domain=funds_etfs" / f"update_run={run_id}" / f"metric={metric_path}" / "part-0.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        relative = path.relative_to(root).as_posix()
        locator_field = "source_partition_locator" if layer == "source_observations" else "fact_partition_locator"
        for row in group:
            row[locator_field] = relative
        ordered = sorted(
            group,
            key=lambda row: (
                str(row.get("event_date_or_period") or row.get("economic_time")),
                str(row.get("subject_id") or row.get("entity_key")),
            ),
        )
        pq.write_table(
            pa.Table.from_pylist(ordered), path,
            compression="zstd", row_group_size=10_000,
        )
        entry = _manifest_entry(path, root, layer, len(group), created_at); entries.append(entry)
        if layer == "standard_facts":
            parquet = pq.ParquetFile(path)
            for rg in range(parquet.metadata.num_row_groups):
                batch = parquet.read_row_group(rg, columns=["subject_type", "subject_id", "metric_id", "economic_time"]).to_pylist()
                grouped: dict[tuple[str, str, str], list[str]] = {}
                for row in batch: grouped.setdefault((row["subject_type"], row["subject_id"], row["metric_id"]), []).append(row["economic_time"])
                for (stype, sid, mid), dates in grouped.items():
                    locatable.append({"subject_type": stype, "subject_id": sid, "metric_id": mid, "time_start": min(dates), "time_end": max(dates), "relative_path": entry["relative_path"], "content_sha256": entry["content_sha256"], "row_group_start": rg, "row_group_end": rg})
    return entries, locatable


def recover_staged_increment(
    context: FundUpdateContext,
    output_root: Path,
    target_stage: Path,
    *,
    start_date: str,
    completed_through: str,
    existing_backup: Path | None,
) -> tuple[FundUpdateContext, Path | None, dict[str, Any] | None]:
    """Reuse a complete failed-run increment and reaccept its generated Series.

    The failed run's identity transaction was rolled back before head advance.
    Its staged facts may therefore name Series UUIDs that were allocated by FR
    but are no longer present in durable identity state.  We recover only those
    Series after proving their subject/metric bindings from the staged facts.
    """
    candidates = []
    for checkpoint in output_root.glob("runs/*/acquisition_checkpoint_v1.json"):
        run_root = checkpoint.parent
        if (run_root / "result_v1.json").exists():
            continue
        recovery = inspect_fund_recovery_candidate(
            run_root,
            start_date=start_date,
            completed_through=completed_through,
        )
        if recovery.get("status") == "reusable":
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            candidates.append((run_root.stat().st_mtime, run_root, payload, run_root / "staged_increment"))
    if not candidates:
        return context, existing_backup, None
    _mtime, run_root, checkpoint, source_stage = max(candidates)
    source_entries: list[dict[str, Any]] = []
    fact_entries: list[dict[str, Any]] = []
    locator_material: list[dict[str, Any]] = []
    series_bindings: dict[str, tuple[str, str, str]] = {}
    created_at = utc_now()
    # A successor-local control SQLite is a delta, not a complete subject
    # registry.  Resolve only the subject references present in this staged
    # increment through the pinned effective view, while also admitting
    # subjects onboarded by the current retry before its delta is written.
    effective_view = _fund_control_view(context.head.snapshot_id)
    local_subjects = {
        (str(row["subject_type"]), str(row["subject_id"]))
        for row in context.new_subjects
    }
    accepted_subject_cache: dict[tuple[str, str], str | None] = {}

    def source_subject_reference(row: Mapping[str, Any]) -> tuple[str, str] | None:
        for field in ("subject_candidate", "source_trace_json"):
            value = row.get(field)
            if not value:
                continue
            try:
                payload = json.loads(str(value))
            except (TypeError, ValueError):
                continue
            subject_type = payload.get("subject_type") or payload.get("canonical_subject_type")
            subject_id = payload.get("subject_id") or payload.get("canonical_subject_id")
            if subject_type and subject_id:
                return str(subject_type), str(subject_id)
        return None

    def subject_is_accepted(subject_type: str, subject_id: str) -> str | None:
        key = (subject_type, subject_id)
        if key in local_subjects:
            return "local"
        if key not in accepted_subject_cache:
            accepted_subject_cache[key] = (
                "inherited" if effective_view.subject(*key) is not None else None
            )
        return accepted_subject_cache[key]

    dropped_orphan_rows = 0
    dropped_orphan_subject_ids: set[str] = set()
    retained_inherited_rows = 0
    retained_local_rows = 0
    source_values: dict[tuple[str, str, str], set[str]] = {}
    promoted_conflict_coordinates: set[tuple[str, str, str]] = set()
    for source_path in sorted(source_stage.rglob("*.parquet")):
        relative = source_path.relative_to(source_stage)
        target = target_stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        layer = relative.parts[0]
        source_parquet = pq.ParquetFile(source_path)
        source_table = source_parquet.read()
        source_rows = source_table.to_pylist()
        references = [
            source_subject_reference(row)
            if layer == "source_observations"
            else (str(row["subject_type"]), str(row["subject_id"]))
            for row in source_rows
        ]
        dispositions = [
            subject_is_accepted(*reference) if reference is not None else None
            for reference in references
        ]
        keep = [disposition is not None for disposition in dispositions]
        retained_inherited_rows += dispositions.count("inherited")
        retained_local_rows += dispositions.count("local")
        if all(keep):
            if not target.exists():
                os.link(source_path, target)
            retained_table = source_table
        else:
            dropped_orphan_rows += keep.count(False)
            dropped_orphan_subject_ids.update(
                reference[1] if reference is not None else "<missing-subject-reference>"
                for reference, retained in zip(references, keep) if not retained
            )
            target.unlink(missing_ok=True)
            retained_table = source_table.filter(pa.array(keep))
            pq.write_table(retained_table, target, compression="zstd", row_group_size=10_000)
        parquet = pq.ParquetFile(target)
        entry = _manifest_entry(target, target_stage, layer, parquet.metadata.num_rows, created_at)
        if layer == "source_observations":
            source_entries.append(entry)
            for row in retained_table.select([
                "entity_key", "metric_id", "event_date_or_period", "raw_value_json"
            ]).to_pylist():
                coordinate = (
                    str(row["entity_key"]), str(row["metric_id"]),
                    str(row["event_date_or_period"]),
                )
                source_values.setdefault(coordinate, set()).add(str(row["raw_value_json"]))
            continue
        fact_entries.append(entry)
        for row_group in range(parquet.metadata.num_row_groups):
            rows = parquet.read_row_group(
                row_group,
                columns=["subject_type", "subject_id", "series_id", "metric_id", "economic_time"],
            ).to_pylist()
            grouped: dict[tuple[str, str, str], list[str]] = {}
            for row in rows:
                key = (row["subject_type"], row["subject_id"], row["metric_id"])
                prior = series_bindings.setdefault(str(row["series_id"]), key)
                if prior != key:
                    raise FundUpdateError(f"staged Series has inconsistent ownership: {row['series_id']}")
                grouped.setdefault(key, []).append(row["economic_time"])
                coordinate = (
                    str(row["subject_id"]), str(row["metric_id"]),
                    str(row["economic_time"]),
                )
                if len(source_values.get(coordinate, ())) > 1:
                    promoted_conflict_coordinates.add(coordinate)
            for (subject_type, subject_id, metric_id), dates in grouped.items():
                locator_material.append({
                    "subject_type": subject_type, "subject_id": subject_id,
                    "metric_id": metric_id, "time_start": min(dates), "time_end": max(dates),
                    "relative_path": entry["relative_path"], "content_sha256": entry["content_sha256"],
                    "row_group_start": row_group, "row_group_end": row_group,
                })

    identity = InstallationIdentityState(resolve_identity_state_path(), resolve_identity_state_backup_root())
    with closing(sqlite3.connect(resolve_identity_state_path())) as connection:
        existing_series = {
            str(row[0]) for row in connection.execute(
                "SELECT subject_id FROM identity_decision_assignment WHERE subject_type='series'"
            )
        }
    missing = sorted(set(series_bindings) - existing_series)
    backup = existing_backup or (identity.backup() if missing else None)
    decisions = identity.create_decisions_batch([
        {
            "subject_type": "series", "existing_subject_id": series_id,
            "accepted_identity_statement": f"Recovered canonical {series_bindings[series_id][2]} Series for accepted {series_bindings[series_id][0]} {series_bindings[series_id][1]}",
            "economic_object_type": "canonical_metric_series",
            "provenance_refs": [str(run_root / "acquisition_checkpoint_v1.json"), "config/metrics_registry.json"],
            "decision_attributes": {"metric_id": series_bindings[series_id][2], "recovered_failed_run_series": True},
        }
        for series_id in missing
    ])
    now = utc_now(); subjects = list(context.new_subjects)
    relationships = list(context.new_relationships); changes = list(context.identity_changes)
    bindings = dict(context.series_bindings)
    for decision, series_id in zip(decisions, missing):
        subject_type, subject_id, metric = series_bindings[series_id]
        attrs = {"display_name": f"{metric} Series", "economic_object_type": "canonical_metric_series", "identity_contract": "installation_local_standard_id_ready", "identity_decision_id": decision["identity_decision_id"], "jurisdiction": "CN", "universe": "Fund", "metric_id": metric, "series_dimensions": {}}
        subjects.append({"subject_type": "series", "subject_id": series_id, "domain": "funds_etfs", "legacy_alias": None, "market": "CN", "venue": None, "effective_start": None, "effective_end": None, "code_aliases_json": "[]", "attributes_json": canonical_json(attrs), "resolution_status": "accepted_canonical_unpublished", "updated_at_utc": now})
        relationships.append(canonical_relationship_record(from_type="series", from_id=series_id, to_type=subject_type, to_id=subject_id, relationship_type="series_of", definition_ref="FR_DATA_GUARDRAILS#series_of", effective_start=None, effective_end=None, provenance_refs=[str(run_root / "acquisition_checkpoint_v1.json"), "config/metrics_registry.json"], attributes={"metric_id": metric, "series_dimensions": {}}, updated_at_utc=now))
        bindings[(subject_type, subject_id, metric)] = series_id
        changes.append({"change_type": "recovered_series_from_failed_increment", "subject_type": subject_type, "subject_id": subject_id, "metric_id": metric, "series_id": series_id, "identity_decisions_created": 1})
    conflict_coordinates = sorted(
        coordinate for coordinate, values in source_values.items() if len(values) > 1
    )
    if promoted_conflict_coordinates:
        raise FundUpdateError(
            "failed increment contains promoted facts for contradictory source values"
        )
    return replace(
        context, series_bindings=bindings, new_subjects=tuple(subjects),
        new_relationships=tuple(relationships), identity_changes=tuple(changes),
    ), backup, {
        "source_run_id": checkpoint["run_id"], "source_run_root": str(run_root),
        "source_entries": source_entries, "fact_entries": fact_entries,
        "locator_material": locator_material,
        "source_row_count": sum(int(row["row_count"]) for row in source_entries),
        "fact_row_count": sum(int(row["row_count"]) for row in fact_entries),
        "series_identities_recovered": len(missing),
        "effective_subject_references_checked": len(accepted_subject_cache),
        "inherited_subject_rows_retained": retained_inherited_rows,
        "local_subject_rows_retained": retained_local_rows,
        "rolled_back_subject_rows_excluded": dropped_orphan_rows,
        "rolled_back_subject_ids_excluded": sorted(dropped_orphan_subject_ids),
        "conflicting_logical_fact_count": len(conflict_coordinates),
        "conflict_examples": [
            {
                "subject_id": subject_id, "metric_id": metric_id,
                "economic_date": economic_date,
                "values": sorted(source_values[(subject_id, metric_id, economic_date)]),
            }
            for subject_id, metric_id, economic_date in conflict_coordinates[:20]
        ],
        "promoted_conflicting_fact_count": 0,
        "incremental_payload_bytes_reused": sum(int(row["byte_count"]) for row in source_entries + fact_entries),
        "historical_payload_rows_scanned": 0,
    }


def load_cached_unknown_valuation_rows(
    context: FundUpdateContext,
    output_root: Path,
    *,
    start_date: str,
    end_date: str,
    include_pairs: Iterable[tuple[str, str]] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Recover unknown or explicitly requested rows from retained responses."""
    included = set(include_pairs)
    by_day_parent: dict[tuple[str, Path], list[Path]] = {}
    for path in output_root.rglob("csrc_valuation_????-??-??_????-??-??_all_*.json"):
        match = re.match(r"csrc_valuation_(\d{4}-\d{2}-\d{2})_", path.name)
        if not match or not (start_date <= match.group(1) <= end_date):
            continue
        by_day_parent.setdefault((match.group(1), path.parent), []).append(path)
    selected: dict[str, list[Path]] = {}
    for (day, _parent), paths in sorted(by_day_parent.items()):
        if day not in selected or len(paths) > len(selected[day]):
            selected[day] = sorted(paths)
    expected_days = []
    cursor, finish = date.fromisoformat(start_date), date.fromisoformat(end_date)
    while cursor <= finish:
        if cursor.weekday() < 5:
            expected_days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    missing_days = sorted(set(expected_days) - set(selected))
    if missing_days:
        return [], {"result": "unavailable", "missing_cached_business_days": missing_days}

    rows: list[dict[str, Any]] = []
    response_files = 0; response_bytes = 0
    seen_records: set[str] = set()
    for day in expected_days:
        for path in selected[day]:
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if not path.stem.endswith(digest[:12]):
                raise FundUpdateError(f"retained CSRC response hash mismatch: {path}")
            response_files += 1; response_bytes += len(content)
            payload = json.loads(content.decode("utf-8"))
            for row in payload.get("aaData") or []:
                fund_id = str((row.get("fund") or {}).get("idStr") or "")
                code = str(row.get("code") or "").zfill(6)
                if (fund_id, code) in context.share_class_bindings and (fund_id, code) not in included:
                    continue
                record_key = hashlib.sha256(canonical_json(row).encode()).hexdigest()
                if record_key not in seen_records:
                    rows.append(dict(row)); seen_records.add(record_key)
    pairs = {
        (str((row.get("fund") or {}).get("idStr") or ""), str(row.get("code") or "").zfill(6))
        for row in rows
    }
    return rows, {
        "result": "reused_verified_failed_run_responses",
        "covered_business_days": expected_days,
        "response_file_count": response_files,
        "response_bytes_read": response_bytes,
        "unknown_pair_count": len(pairs),
        "unknown_record_count": len(rows),
        "historical_fund_payload_rows_scanned": 0,
    }


def _copy_query_control(snapshot_control: Path, query_control: Path) -> None:
    """Publish one byte-identical query copy from a closed SQLite owner."""
    query_control.parent.mkdir(parents=True, exist_ok=True)
    query_control.unlink(missing_ok=True)
    shutil.copy2(snapshot_control, query_control)


def _fund_control_view(snapshot_id: str) -> IncrementalControlView:
    return IncrementalControlView(
        snapshot_id,
        control_path=lambda value: resolve_unpublished_snapshot_path(value) / FUND_CONTROL,
        manifest_path=lambda value: resolve_unpublished_snapshot_path(value) / MANIFEST,
        control_relative_path=FUND_CONTROL,
    )


def _insert_records(
    connection: sqlite3.Connection,
    table: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    replace_existing: bool = False,
) -> int:
    count = 0
    verb = "INSERT OR REPLACE" if replace_existing else "INSERT"
    for source in rows:
        row = dict(source)
        columns = tuple(row)
        connection.execute(
            f"{verb} INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            tuple(row[column] for column in columns),
        )
        count += 1
    return count


def _effective_delta_state(
    view: IncrementalControlView,
    table: str,
    key_column: str,
    *,
    tombstone_kind: str,
    snapshot_scoped: bool = False,
    newest_rows: Iterable[Mapping[str, Any]] = (),
) -> dict[str, dict[str, Any] | None]:
    """Resolve only post-checkpoint rows; never enumerate the complete base."""
    state: dict[str, dict[str, Any] | None] = {
        str(row[key_column]): dict(row) for row in newest_rows
    }
    for layer in view.layers:
        if layer.is_checkpoint:
            continue
        with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if exists:
                sql = f"SELECT * FROM {table}"
                params: tuple[Any, ...] = ()
                if snapshot_scoped:
                    sql += " WHERE snapshot_id=?"
                    params = (layer.snapshot_id,)
                for stored in connection.execute(sql, params):
                    row = dict(stored)
                    state.setdefault(str(row[key_column]), row)
            tombstone_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_record_tombstone'"
            ).fetchone()
            if tombstone_table:
                for (record_key,) in connection.execute(
                    "SELECT record_key FROM control_record_tombstone WHERE record_kind=?",
                    (tombstone_kind,),
                ):
                    state.setdefault(str(record_key), None)
    return state


def _write_compacted_control_overlay(
    context: FundUpdateContext,
    control: Path,
    *,
    predecessor_view: IncrementalControlView,
    successor_id: str,
    created_at: str,
    manifest_entries: Sequence[Mapping[str, Any]],
    locator_material: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Roll post-checkpoint deltas into one immutable overlay.

    The complete accepted checkpoint remains the base.  Only records changed
    since that checkpoint are reread and rewritten, so chain depth is bounded
    without turning a fixed version count into a recurring full-control copy.
    """
    base = next((layer for layer in predecessor_view.layers if layer.is_checkpoint), None)
    if base is None:
        raise FundUpdateError("control overlay compaction has no complete base checkpoint")
    delta_layers = [layer for layer in predecessor_view.layers if not layer.is_checkpoint]
    control.unlink(missing_ok=True)
    control.parent.mkdir(parents=True, exist_ok=True)

    subject_state = _effective_delta_state(
        predecessor_view, "subject_registry", "subject_id", tombstone_kind="subject",
        newest_rows=context.new_subjects,
    )
    alias_state = _effective_delta_state(
        predecessor_view, "subject_alias_registry", "alias_id", tombstone_kind="alias",
        newest_rows=context.new_aliases,
    )
    relationship_state = _effective_delta_state(
        predecessor_view, "subject_relationship_registry", "relationship_id",
        tombstone_kind="relationship", newest_rows=context.new_relationships,
    )
    locator_state = _effective_delta_state(
        predecessor_view, "subject_partition_locator_registry", "locator_id",
        tombstone_kind="locator", snapshot_scoped=True,
    )
    nonpromoted_state = _effective_delta_state(
        predecessor_view, "fund_nonpromoted_interval_index", "record_id",
        tombstone_kind="fund_nonpromoted", snapshot_scoped=True,
    )
    subjects = [row for row in subject_state.values() if row is not None]
    visibility_cache: dict[tuple[str, str], bool] = {}

    def subject_visible(subject_type: str, subject_id: str) -> bool:
        key = (str(subject_type), str(subject_id))
        if key not in visibility_cache:
            local = subject_state.get(key[1], "not_in_delta")
            visibility_cache[key] = (
                local is not None if local != "not_in_delta"
                else predecessor_view.subject(*key) is not None
            )
        return visibility_cache[key]

    aliases = [
        row for row in alias_state.values() if row is not None
        and subject_visible(str(row["subject_type"]), str(row["subject_id"]))
    ]
    relationships = [
        row for row in relationship_state.values() if row is not None
        and subject_visible(str(row["from_type"]), str(row["from_id"]))
        and subject_visible(str(row["to_type"]), str(row["to_id"]))
    ]
    successor_members = {
        str(row["relative_path"]): (str(row["layer_name"]), str(row["content_sha256"]))
        for row in manifest_entries
    }
    inherited_locators: list[dict[str, Any]] = []
    for row in locator_state.values():
        if row is None or not subject_visible(str(row["subject_type"]), str(row["subject_id"])) or successor_members.get(str(row["relative_path"])) != (
            str(row["layer_name"]), str(row["content_sha256"])
        ):
            continue
        inherited_locators.append(canonical_locator_record(
            snapshot_id=successor_id, layer_name=str(row["layer_name"]),
            subject_type=str(row["subject_type"]), subject_id=str(row["subject_id"]),
            metric_id=row.get("metric_id"), scope=json.loads(str(row["scope_json"])),
            time_start=row.get("time_start"), time_end=row.get("time_end"),
            relative_path=str(row["relative_path"]), content_sha256=str(row["content_sha256"]),
            row_group_start=row.get("row_group_start"), row_group_end=row.get("row_group_end"),
            updated_at_utc=created_at,
        ))
    locators = inherited_locators + [canonical_locator_record(
        snapshot_id=successor_id, layer_name="standard_facts",
        scope={"dataset": DATASET_NAME, "jurisdiction": "CN", "universe": "Fund"},
        updated_at_utc=created_at, **dict(row),
    ) for row in locator_material]

    affected_search: set[tuple[str, str]] = {
        (str(row["subject_type"]), str(row["subject_id"]))
        for row in list(context.new_subjects) + list(context.new_aliases)
    }
    for layer in delta_layers:
        with closing(sqlite3.connect(f"file:{layer.control_path.as_posix()}?mode=ro", uri=True)) as connection:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_subject_override'"
            ).fetchone()
            if exists:
                affected_search.update(
                    (str(row[0]), str(row[1])) for row in connection.execute(
                        "SELECT subject_type,subject_id FROM control_subject_override WHERE record_kind='fund_search'"
                    )
                )
    local_subject_map = {
        (str(row["subject_type"]), str(row["subject_id"])): row for row in subjects
    }
    local_aliases_by_subject: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in aliases:
        local_aliases_by_subject.setdefault(
            (str(row["subject_type"]), str(row["subject_id"])), []
        ).append(row)
    search_subjects: list[dict[str, Any]] = []
    search_aliases: list[dict[str, Any]] = []
    for key in sorted(affected_search):
        subject = local_subject_map.get(key) or predecessor_view.subject(*key)
        if subject is None:
            continue
        search_subjects.append(subject)
        local = local_aliases_by_subject.get(key, [])
        local_ids = {str(row["alias_id"]) for row in local}
        search_aliases.extend(local)
        search_aliases.extend(
            row for row in predecessor_view.aliases(*key)
            if str(row["alias_id"]) not in local_ids
        )

    watermarks = predecessor_view.watermarks(ALL_METRICS)
    for locator in locators:
        if locator.get("metric_id") and locator.get("time_end"):
            key = (str(locator["subject_type"]), str(locator["subject_id"]), str(locator["metric_id"]))
            watermarks[key] = max(watermarks.get(key, ""), str(locator["time_end"]))

    with closing(sqlite3.connect(control)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE snapshot_catalog(snapshot_id TEXT PRIMARY KEY,predecessor_snapshot_id TEXT,created_at_utc TEXT)"
        )
        connection.execute(
            "CREATE TABLE partition_manifest(partition_id TEXT PRIMARY KEY,layer_name TEXT NOT NULL,relative_path TEXT NOT NULL UNIQUE,row_count INTEGER NOT NULL,byte_count INTEGER NOT NULL,content_sha256 TEXT NOT NULL,completed INTEGER NOT NULL)"
        )
        ensure_semantic_control_schema(connection)
        ensure_fund_query_schema(connection)
        ensure_control_watermark_schema(connection)
        initialize_delta(
            connection, snapshot_id=successor_id,
            predecessor_snapshot_id=base.snapshot_id,
            predecessor_manifest_sha256=sha256_file(base.manifest_path),
            predecessor_control_sha256=control_member_hash(base.manifest_path, FUND_CONTROL),
            base_checkpoint_snapshot_id=base.snapshot_id, created_at_utc=created_at,
        )
        connection.execute(
            "INSERT INTO snapshot_catalog VALUES (?,?,?)",
            (successor_id, context.head.snapshot_id, created_at),
        )
        connection.executemany(
            "INSERT INTO partition_manifest VALUES (?,?,?,?,?,?,?)",
            [(row["partition_id"], row["layer_name"], row["relative_path"], int(row["row_count"]),
              int(row["byte_count"]), row["content_sha256"], 1) for row in manifest_entries],
        )
        _insert_records(connection, "subject_registry", subjects)
        _insert_records(connection, "subject_alias_registry", aliases)
        _insert_records(connection, "subject_relationship_registry", relationships)
        register_locators_batch(
            connection, locators,
            subject_exists=lambda subject_type, subject_id: (
                (str(subject_type), str(subject_id)) in local_subject_map
                or predecessor_view.subject(str(subject_type), str(subject_id)) is not None
            ),
        )
        nonpromoted_rows = [{
            "subject_type": row.get("subject_type"), "subject_id": row.get("subject_id"),
            "external_code": row.get("external_code"), "metric_id": row.get("metric_id"),
            "time_start": row.get("time_start"), "time_end": row.get("time_end"),
            "row_count": row.get("row_count"), "reason": row["reason"],
            "evidence_refs": json.loads(str(row["evidence_json"])),
        } for row in nonpromoted_state.values() if row is not None and (
            row.get("subject_type") is None or row.get("subject_id") is None
            or subject_visible(str(row["subject_type"]), str(row["subject_id"]))
        )]
        replace_nonpromoted_interval_index(connection, successor_id, nonpromoted_rows)
        add_subject_overrides(
            connection, "fund_search", affected_search, created_at_utc=created_at
        )
        search_rows = write_fund_search_delta(
            connection, successor_id, search_subjects, search_aliases
        )
        tombstones = []
        for kind, state in (
            ("subject", subject_state), ("alias", alias_state),
            ("relationship", relationship_state), ("locator", locator_state),
            ("fund_nonpromoted", nonpromoted_state),
        ):
            tombstones.extend({
                "record_kind": kind, "record_key": key,
                "reason": "preserved_by_delta_overlay_compaction",
                "created_at_utc": created_at,
            } for key, value in state.items() if value is None)
        add_tombstones(connection, tombstones)
        connection.executemany(
            "INSERT INTO control_series_watermark VALUES (?,?,?,?)",
            [(*key, value) for key, value in sorted(watermarks.items())],
        )
        connection.execute("INSERT INTO control_watermark_state VALUES (1,1)")
        connection.commit()
    delta_bytes_read = sum(layer.control_path.stat().st_size for layer in delta_layers)
    return {
        "control_representation": "compacted_delta_overlay",
        "local_subject_rows": len(subjects), "local_alias_rows": len(aliases),
        "local_relationship_rows": len(relationships), "local_locator_rows": len(locators),
        "local_search_rows": search_rows, "local_watermark_rows": len(watermarks),
        "complete_watermark_checkpoint_created": 1,
        "historical_locator_rows_copied": len(inherited_locators),
        "inherited_locator_rows_rematerialized": len(inherited_locators),
        "complete_search_rows_rebuilt": 0,
        "inherited_search_rows_rematerialized": search_rows,
        "full_base_control_rows_materialized": 0,
        "base_locator_rows_materialized": 0,
        "delta_control_bytes_read": delta_bytes_read,
        "control_bytes_written": control.stat().st_size,
        "large_control_sqlite_bytes_copied": 0,
        "predecessor_control_chain_depth": predecessor_view.depth,
        "control_chain_depth": 2,
        "historical_business_payload_rows_read": 0,
    }


def _write_complete_control_checkpoint(
    context: FundUpdateContext,
    control: Path,
    *,
    predecessor_view: IncrementalControlView,
    successor_id: str,
    created_at: str,
    manifest_entries: Sequence[Mapping[str, Any]],
    locator_material: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    """Flatten only effective compact control state at a bounded chain threshold."""
    control.unlink(missing_ok=True)
    control.parent.mkdir(parents=True, exist_ok=True)
    subjects = {
        (str(row["subject_type"]), str(row["subject_id"])): dict(row)
        for row in predecessor_view.subjects()
    }
    subjects.update({
        (str(row["subject_type"]), str(row["subject_id"])): dict(row)
        for row in context.new_subjects
    })
    aliases = {
        str(row["alias_id"]): dict(row)
        for row in predecessor_view.effective_rows(
            "subject_alias_registry", "alias_id", tombstone_kind="alias"
        )
    }
    aliases.update({str(row["alias_id"]): dict(row) for row in context.new_aliases})
    aliases = {
        key: row for key, row in aliases.items()
        if (str(row["subject_type"]), str(row["subject_id"])) in subjects
    }
    relationships = {
        str(row["relationship_id"]): dict(row)
        for row in predecessor_view.effective_rows(
            "subject_relationship_registry", "relationship_id",
            tombstone_kind="relationship",
        )
    }
    relationships.update({
        str(row["relationship_id"]): dict(row) for row in context.new_relationships
    })
    relationships = {
        key: row for key, row in relationships.items()
        if (str(row["from_type"]), str(row["from_id"])) in subjects
        and (str(row["to_type"]), str(row["to_id"])) in subjects
    }
    inherited_locators = predecessor_view.effective_rows(
        "subject_partition_locator_registry", "locator_id",
        snapshot_scoped=True, tombstone_kind="locator",
    )
    successor_members = {
        str(row["relative_path"]): (str(row["layer_name"]), str(row["content_sha256"]))
        for row in manifest_entries
    }
    locators: dict[str, dict[str, Any]] = {}
    for row in inherited_locators:
        if (str(row["subject_type"]), str(row["subject_id"])) not in subjects:
            continue
        if successor_members.get(str(row["relative_path"])) != (
            str(row["layer_name"]), str(row["content_sha256"])
        ):
            continue
        canonical = canonical_locator_record(
            snapshot_id=successor_id,
            layer_name=str(row["layer_name"]),
            subject_type=str(row["subject_type"]),
            subject_id=str(row["subject_id"]),
            metric_id=row.get("metric_id"),
            scope=json.loads(str(row["scope_json"])),
            time_start=row.get("time_start"),
            time_end=row.get("time_end"),
            relative_path=str(row["relative_path"]),
            content_sha256=str(row["content_sha256"]),
            row_group_start=row.get("row_group_start"),
            row_group_end=row.get("row_group_end"),
            updated_at_utc=created_at,
        )
        locators[str(canonical["locator_id"])] = canonical
    for row in locator_material:
        canonical = canonical_locator_record(
            snapshot_id=successor_id,
            layer_name="standard_facts",
            scope={"dataset": DATASET_NAME, "jurisdiction": "CN", "universe": "Fund"},
            updated_at_utc=created_at,
            **dict(row),
        )
        locators[str(canonical["locator_id"])] = canonical
    nonpromoted = predecessor_view.effective_rows(
        "fund_nonpromoted_interval_index", "record_id",
        snapshot_scoped=True, tombstone_kind="fund_nonpromoted",
    )
    watermarks = predecessor_view.watermarks(ALL_METRICS)
    for locator in locators.values():
        if locator.get("metric_id") and locator.get("time_end"):
            key = (
                str(locator["subject_type"]), str(locator["subject_id"]),
                str(locator["metric_id"]),
            )
            watermarks[key] = max(watermarks.get(key, ""), str(locator["time_end"]))
    with closing(sqlite3.connect(control)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE snapshot_catalog(snapshot_id TEXT PRIMARY KEY,predecessor_snapshot_id TEXT,created_at_utc TEXT)"
        )
        connection.execute(
            "CREATE TABLE partition_manifest(partition_id TEXT PRIMARY KEY,layer_name TEXT NOT NULL,relative_path TEXT NOT NULL UNIQUE,row_count INTEGER NOT NULL,byte_count INTEGER NOT NULL,content_sha256 TEXT NOT NULL,completed INTEGER NOT NULL)"
        )
        ensure_semantic_control_schema(connection)
        ensure_fund_query_schema(connection)
        ensure_control_watermark_schema(connection)
        connection.execute(
            "INSERT INTO snapshot_catalog VALUES (?,?,?)",
            (successor_id, context.head.snapshot_id, created_at),
        )
        connection.executemany(
            "INSERT INTO partition_manifest VALUES (?,?,?,?,?,?,?)",
            [
                (
                    row["partition_id"], row["layer_name"], row["relative_path"],
                    int(row["row_count"]), int(row["byte_count"]),
                    row["content_sha256"], 1,
                )
                for row in manifest_entries if row["relative_path"] != FUND_CONTROL
            ],
        )
        _insert_records(connection, "subject_registry", subjects.values())
        _insert_records(connection, "subject_alias_registry", aliases.values())
        _insert_records(connection, "subject_relationship_registry", relationships.values())
        register_locators_batch(
            connection, locators.values(),
            subject_exists=lambda subject_type, subject_id: (
                (str(subject_type), str(subject_id)) in subjects
            ),
        )
        nonpromoted_rows = [
            {
                "subject_type": row.get("subject_type"),
                "subject_id": row.get("subject_id"),
                "external_code": row.get("external_code"),
                "metric_id": row.get("metric_id"),
                "time_start": row.get("time_start"),
                "time_end": row.get("time_end"),
                "row_count": row.get("row_count"),
                "reason": row["reason"],
                "evidence_refs": json.loads(str(row["evidence_json"])),
            }
            for row in nonpromoted
            if (str(row["subject_type"]), str(row["subject_id"])) in subjects
        ]
        replace_nonpromoted_interval_index(connection, successor_id, nonpromoted_rows)
        search_rows = rebuild_fund_search_index(connection, successor_id)
        connection.executemany(
            "INSERT INTO control_series_watermark VALUES (?,?,?,?)",
            [(*key, value) for key, value in sorted(watermarks.items())],
        )
        connection.execute("INSERT INTO control_watermark_state VALUES (1,1)")
        connection.commit()
    return {
        "control_representation": "complete_checkpoint",
        "local_subject_rows": len(subjects),
        "local_alias_rows": len(aliases),
        "local_relationship_rows": len(relationships),
        "local_locator_rows": len(locators),
        "local_search_rows": search_rows,
        "local_watermark_rows": len(watermarks),
        "complete_watermark_checkpoint_created": 1,
        "historical_locator_rows_copied": len(inherited_locators),
        "inherited_locator_rows_rematerialized": len(inherited_locators),
        "effective_control_rows_materialized": (
            len(subjects) + len(aliases) + len(relationships) + len(locators)
            + search_rows + len(nonpromoted) + len(watermarks)
        ),
        "complete_search_rows_rebuilt": search_rows,
        "inherited_search_rows_rematerialized": search_rows,
        "large_control_sqlite_bytes_copied": 0,
        "predecessor_control_chain_depth": predecessor_view.depth,
        "control_chain_depth": 1,
        "control_bytes_written": control.stat().st_size,
        "historical_business_payload_rows_read": 0,
    }


def _write_incremental_control(
    context: FundUpdateContext,
    control: Path,
    *,
    successor_id: str,
    created_at: str,
    manifest_entries: Sequence[Mapping[str, Any]],
    locator_material: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Create one successor-local delta; never copy the predecessor control DB."""
    predecessor_manifest = context.predecessor_root / MANIFEST
    predecessor_view = _fund_control_view(context.head.snapshot_id)
    if predecessor_view.depth >= MAX_CONTROL_CHAIN_DEPTH:
        delta_layers = [layer for layer in predecessor_view.layers if not layer.is_checkpoint]
        base = next(layer for layer in predecessor_view.layers if layer.is_checkpoint)
        delta_bytes = sum(layer.control_path.stat().st_size for layer in delta_layers)
        # A complete checkpoint is maintenance proportional to accumulated
        # change, never a fixed-version tax.  Below the ratio, compact only the
        # post-checkpoint overlay and leave the 2+ GB accepted base untouched.
        if delta_bytes < base.control_path.stat().st_size * FULL_CONTROL_CHECKPOINT_DELTA_RATIO:
            return _write_compacted_control_overlay(
                context, control, predecessor_view=predecessor_view,
                successor_id=successor_id, created_at=created_at,
                manifest_entries=manifest_entries, locator_material=locator_material,
            )
        result = _write_complete_control_checkpoint(
            context, control, predecessor_view=predecessor_view,
            successor_id=successor_id, created_at=created_at,
            manifest_entries=manifest_entries, locator_material=locator_material,
        )
        result["consolidation_trigger"] = "accumulated_delta_bytes_at_least_25_percent_of_base"
        result["accumulated_delta_control_bytes"] = delta_bytes
        result["base_control_bytes"] = base.control_path.stat().st_size
        return result
    control.unlink(missing_ok=True)
    control.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(control)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE snapshot_catalog(snapshot_id TEXT PRIMARY KEY,predecessor_snapshot_id TEXT,created_at_utc TEXT)"
        )
        connection.execute(
            "CREATE TABLE partition_manifest(partition_id TEXT PRIMARY KEY,layer_name TEXT NOT NULL,relative_path TEXT NOT NULL UNIQUE,row_count INTEGER NOT NULL,byte_count INTEGER NOT NULL,content_sha256 TEXT NOT NULL,completed INTEGER NOT NULL)"
        )
        ensure_semantic_control_schema(connection)
        ensure_fund_query_schema(connection)
        initialize_delta(
            connection,
            snapshot_id=successor_id,
            predecessor_snapshot_id=context.head.snapshot_id,
            predecessor_manifest_sha256=context.head.snapshot_manifest_sha256,
            predecessor_control_sha256=control_member_hash(predecessor_manifest, FUND_CONTROL),
            base_checkpoint_snapshot_id=base_checkpoint_snapshot_id(
                context.control_path, context.head.snapshot_id
            ),
            created_at_utc=created_at,
        )
        connection.execute(
            "INSERT INTO snapshot_catalog VALUES (?,?,?)",
            (successor_id, context.head.snapshot_id, created_at),
        )
        connection.executemany(
            "INSERT INTO partition_manifest VALUES (?,?,?,?,?,?,?)",
            [
                (
                    row["partition_id"], row["layer_name"], row["relative_path"],
                    int(row["row_count"]), int(row["byte_count"]),
                    row["content_sha256"], 1,
                )
                for row in manifest_entries
            ],
        )
        for row in context.new_subjects:
            columns = tuple(row)
            connection.execute(
                f"INSERT INTO subject_registry({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                tuple(row[column] for column in columns),
            )
        for table, rows in (
            ("subject_alias_registry", context.new_aliases),
            ("subject_relationship_registry", context.new_relationships),
        ):
            for row in rows:
                columns = tuple(row)
                connection.execute(
                    f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
                    tuple(row[column] for column in columns),
                )
        additions = [
            canonical_locator_record(
                snapshot_id=successor_id, layer_name="standard_facts",
                scope={"dataset": DATASET_NAME, "jurisdiction": "CN", "universe": "Fund"},
                updated_at_utc=created_at, **dict(row),
            ) for row in locator_material
        ]
        local_subjects = {
            (str(row["subject_type"]), str(row["subject_id"]))
            for row in context.new_subjects
        }
        register_locators_batch(
            connection, additions,
            subject_exists=lambda subject_type, subject_id: (
                (subject_type, subject_id) in local_subjects
                or predecessor_view.subject(subject_type, subject_id) is not None
            ),
        )
        affected = sorted({
            (str(row["subject_type"]), str(row["subject_id"]))
            for row in list(context.new_subjects) + list(context.new_aliases)
        })
        add_subject_overrides(
            connection, "fund_search", affected, created_at_utc=created_at
        )
        local_subject_map = {
            (str(row["subject_type"]), str(row["subject_id"])): dict(row)
            for row in context.new_subjects
        }
        search_subjects = [
            local_subject_map.get(key) or predecessor_view.subject(*key)
            for key in affected
        ]
        search_aliases = list(context.new_aliases)
        new_alias_ids = {str(row["alias_id"]) for row in context.new_aliases}
        for key in affected:
            search_aliases.extend(
                row for row in predecessor_view.aliases(*key)
                if str(row["alias_id"]) not in new_alias_ids
            )
        search_rows = write_fund_search_delta(
            connection, successor_id,
            [row for row in search_subjects if row is not None], search_aliases,
        )
        predecessor_has_watermarks = predecessor_view.has_complete_watermark_checkpoint()
        watermark_rows: dict[tuple[str, str, str], str] = {}
        if not predecessor_has_watermarks and context.watermarks:
            watermark_rows.update({tuple(key): str(value) for key, value in context.watermarks.items()})
            complete_watermark_checkpoint = 1
        else:
            complete_watermark_checkpoint = 0
        # A first incremental update can add newly reconciled Series while the
        # predecessor still has no watermark checkpoint.  Seed the inherited
        # watermarks and then overlay every staged locator so a retry starts
        # after the materialized observations instead of re-ingesting them.
        for row in locator_material:
            if row.get("metric_id") and row.get("time_end"):
                key = (str(row["subject_type"]), str(row["subject_id"]), str(row["metric_id"]))
                watermark_rows[key] = max(watermark_rows.get(key, ""), str(row["time_end"]))
        connection.executemany(
            "INSERT INTO control_series_watermark VALUES (?,?,?,?)",
            [(*key, value) for key, value in sorted(watermark_rows.items())],
        )
        connection.execute(
            "INSERT INTO control_watermark_state VALUES (1,?)",
            (complete_watermark_checkpoint,),
        )
        connection.commit()
    return {
        "control_representation": "successor_local_delta",
        "local_subject_rows": len(context.new_subjects),
        "local_alias_rows": len(context.new_aliases),
        "local_relationship_rows": len(context.new_relationships),
        "local_locator_rows": len(additions),
        "local_search_rows": search_rows,
        "local_watermark_rows": len(watermark_rows),
        "complete_watermark_checkpoint_created": complete_watermark_checkpoint,
        "historical_locator_rows_copied": 0,
        "inherited_locator_rows_rematerialized": 0,
        "complete_search_rows_rebuilt": 0,
        "inherited_search_rows_rematerialized": 0,
        "control_bytes_written": control.stat().st_size,
        "large_control_sqlite_bytes_copied": 0,
        "control_chain_depth": predecessor_view.depth + 1,
    }


def materialize_staged_successor(
    context: FundUpdateContext,
    config: FundUpdateConfig,
    *,
    run_id: str,
    stage_root: Path,
    source_entries: Sequence[Mapping[str, Any]],
    fact_entries: Sequence[Mapping[str, Any]],
    locator_material: Sequence[Mapping[str, Any]],
    source_row_count: int,
    fact_row_count: int,
    reality_evidence: Mapping[str, Any],
    source_receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Promote bounded staged increment files without retaining all rows in RAM."""
    created_at = utc_now()
    digest = hashlib.sha256(canonical_json({
        "predecessor": context.head.snapshot_id,
        "run_id": run_id,
        "fact_members": [(row["relative_path"], row["content_sha256"]) for row in fact_entries],
    }).encode()).hexdigest()[:12]
    successor_id = f"frfundupdate1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{digest}"
    clone = clone_snapshot_from_manifest(context.head.snapshot_id, successor_id)
    root = resolve_unpublished_snapshot_path(successor_id)
    for entry in list(source_entries) + list(fact_entries):
        source = stage_root / entry["relative_path"]
        target = root / entry["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            if source.drive.casefold() == target.drive.casefold():
                os.link(source, target)
            else:
                shutil.copy2(source, target)
    control = root / FUND_CONTROL
    manifest_path = root / MANIFEST
    shutil.copy2(context.predecessor_root / MANIFEST, manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    members = {row["relative_path"]: dict(row) for row in manifest["files"]}
    for entry in list(source_entries) + list(fact_entries):
        members[entry["relative_path"]] = dict(entry)
    evidence_path = root / "metadata/china_public_fund/update_reality_and_source_evidence_v1.json"
    write_json_atomic(evidence_path, {
        "schema_version": "fr_china_public_fund_update_evidence_v1",
        **dict(reality_evidence), "source_receipts": list(source_receipts),
    })
    reality_path = root / FUND_REALITY
    reality = json.loads((context.predecessor_root / FUND_REALITY).read_text(encoding="utf-8"))
    current_listings_path = root / "metadata/china_public_fund/authoritative_current_exchange_listings_v1.ndjson"
    listing_changes = [row for row in context.identity_changes if row.get("listing_id")]
    product_changes = [row for row in context.identity_changes if row.get("change_type") == "new_public_fund_product"]
    share_class_changes = [row for row in context.identity_changes if row.get("change_type") == "new_fund_share_class"]
    incremental_objects_path = root / "metadata/china_public_fund/authoritative_user_update_objects_v1.ndjson"
    incremental_object_rows = product_changes + share_class_changes
    if incremental_object_rows:
        inherited_incremental = _read_ndjson(incremental_objects_path) if incremental_objects_path.exists() else []
        incremental_objects_path.unlink(missing_ok=True)
        by_identity = {
            str(row.get("fund_id") or row.get("share_class_id")): dict(row)
            for row in inherited_incremental + incremental_object_rows
        }
        _write_ndjson(incremental_objects_path, [by_identity[key] for key in sorted(by_identity)])
        relative = incremental_objects_path.relative_to(root).as_posix()
        owner_members = reality.setdefault("authoritative_files", [])
        owner_member = next((row for row in owner_members if row.get("relative_path") == relative), None)
        if owner_member is None:
            owner_member = {"relative_path": relative}
            owner_members.append(owner_member)
        owner_member.update({"bytes": incremental_objects_path.stat().st_size, "sha256": sha256_file(incremental_objects_path)})
    current_listing_changed = False
    current_listing_row_count = 0
    if listing_changes:
        inherited_listing_rows = _read_ndjson(current_listings_path)
        existing_listing_keys = {
            (str(row.get("venue") or ""), str(row.get("exchange_code") or "").zfill(6))
            for row in inherited_listing_rows
        }
        additions: list[dict[str, Any]] = []
        for row in listing_changes:
            key = (str(row["venue"]), str(row["code"]).zfill(6))
            if key in existing_listing_keys:
                continue
            additions.append({
                "csrc_eid_fund_id": row["csrc_eid_fund_id"],
                "csrc_product_sequence": None,
                "exchange_code": row["code"],
                "listing_date": row.get("listing_start_date"),
                "listing_name": row.get("fund_name"),
                "manager_name": row.get("manager_name"),
                "observation_date": config.as_of_date,
                "product_binding_status": "proved",
                "product_structure_code": row.get("product_structure_code"),
                "source_refs": ["SSE_current_fund_list", row.get("source_document_url")],
                "venue": row["venue"],
            })
        if additions:
            current_listings_path.unlink(missing_ok=True)
            _write_ndjson(
                current_listings_path,
                sorted(
                    inherited_listing_rows + additions,
                    key=lambda item: (str(item.get("venue")), str(item.get("exchange_code"))),
                ),
            )
            current_listing_changed = True
            current_listing_row_count = len(inherited_listing_rows) + len(additions)
            relative = current_listings_path.relative_to(root).as_posix()
            for owner_member in reality.get("authoritative_files", []):
                if owner_member.get("relative_path") == relative:
                    owner_member["bytes"] = current_listings_path.stat().st_size
                    owner_member["sha256"] = sha256_file(current_listings_path)
                    break
    reality.update({
        "as_of_date": config.as_of_date,
        # Count economic objects, not the discovery branch that happened to
        # create them.  A new exchange listing may introduce a Fund product
        # and share class in the same accepted object graph.
        "fund_products": int(reality.get("fund_products", 0))
        + sum(row.get("subject_type") == "fund" for row in context.new_subjects),
        "fund_share_classes": int(reality.get("fund_share_classes", 0))
        + sum(row.get("subject_type") == "fund_share_class" for row in context.new_subjects),
        "current_exchange_listings": int(reality.get("current_exchange_listings", 0)) + len(listing_changes),
        "last_user_triggered_update_evidence": evidence_path.relative_to(root).as_posix(),
        "last_user_triggered_update_evidence_sha256": sha256_file(evidence_path),
        "new_identity_objects_in_last_update": list(context.identity_changes),
    })
    reality_path.unlink(missing_ok=True)
    write_json_atomic(reality_path, reality)
    identity_owner_path = root / FUND_IDENTITY
    identity_owner = json.loads(identity_owner_path.read_text(encoding="utf-8"))
    identity_owner.update({
        "subjects": int(identity_owner.get("subjects", 0)) + len(context.new_subjects),
        "aliases": int(identity_owner.get("aliases", 0)) + len(context.new_aliases),
        "relationships": int(identity_owner.get("relationships", 0)) + len(context.new_relationships),
        "decisions_created_in_last_update": sum(int(row["identity_decisions_created"]) for row in context.identity_changes),
        "last_update_identity_changes": list(context.identity_changes),
    })
    identity_owner_path.unlink(missing_ok=True)
    write_json_atomic(identity_owner_path, identity_owner)
    state_path = root / FUND_STATE
    previous_state = json.loads(Path(context.head.state_path).read_text(encoding="utf-8"))
    state = {
        **previous_state,
        "schema_version": "fr_china_public_fund_validated_update_state_v2",
        "predecessor_snapshot_id": context.head.snapshot_id,
        "successor_snapshot_id": successor_id,
        "authoritative_cutoff": config.as_of_date,
        "run_id": run_id,
        "incremental_source_observations": source_row_count,
        "incremental_standard_facts": fact_row_count,
        "source_receipt_count": len(source_receipts),
        "identity_owner_path": str(identity_owner_path),
        "identity_owner_sha256": sha256_file(identity_owner_path),
    }
    state_path.unlink(missing_ok=True)
    write_json_atomic(state_path, state)
    query_contract_path = root / "metadata/china_public_fund/query_contract_v1.json"
    query_contract = json.loads(query_contract_path.read_text(encoding="utf-8"))
    query_contract["snapshot_id"] = successor_id
    write_json_atomic(query_contract_path, query_contract)
    metadata_paths = [
        evidence_path, reality_path, identity_owner_path, state_path,
        query_contract_path,
    ]
    if current_listing_changed:
        metadata_paths.append(current_listings_path)
    if incremental_object_rows:
        metadata_paths.append(incremental_objects_path)
    for path in metadata_paths:
        if path == current_listings_path:
            row_count = current_listing_row_count
        elif path == incremental_objects_path:
            row_count = len(_read_ndjson(incremental_objects_path))
        else:
            row_count = 1
        members[path.relative_to(root).as_posix()] = _manifest_entry(path, root, "metadata", row_count, created_at)
    manifest.update({
        "snapshot_id": successor_id,
        "predecessor_snapshot_id": context.head.snapshot_id,
        "predecessor_manifest_sha256": context.head.snapshot_manifest_sha256,
        "run_id": run_id, "created_at_utc": created_at,
        "reality_cutoff_date": config.as_of_date,
        "publication_state": "unpublished_validated_fund_update",
        "canonical_china_public_fund_fact_rows": int(manifest["canonical_china_public_fund_fact_rows"]) + fact_row_count,
    })
    manifest["files"] = sorted(members.values(), key=lambda row: row["relative_path"])
    manifest["file_count"] = len(manifest["files"])
    manifest["compressed_bytes"] = sum(int(row["byte_count"]) for row in manifest["files"])
    manifest = reconcile_manifest_aggregate_counts(manifest)
    write_json_atomic(manifest_path, manifest)
    control_stats = _write_incremental_control(
        context, control, successor_id=successor_id, created_at=created_at,
        manifest_entries=[
            row for row in manifest["files"]
            if row["layer_name"] in {"source_observations", "standard_facts"}
        ],
        locator_material=locator_material,
    )
    # Snapshot-local owner paths and hashes can only be finalized after the
    # detached control database has committed all subjects and locators.
    control_sha256 = sha256_file(control)
    identity_owner["control_sha256"] = control_sha256
    write_json_atomic(identity_owner_path, identity_owner)
    state.update({
        "snapshot_id": successor_id,
        "control_owner_path": str(control),
        "control_owner_sha256": control_sha256,
        "identity_owner_path": str(identity_owner_path),
        "identity_owner_sha256": sha256_file(identity_owner_path),
        "query_contract_path": str(root / "metadata/china_public_fund/query_contract_v1.json"),
        "query_contract_sha256": sha256_file(root / "metadata/china_public_fund/query_contract_v1.json"),
    })
    write_json_atomic(state_path, state)
    for path in (identity_owner_path, state_path):
        members[path.relative_to(root).as_posix()] = _manifest_entry(
            path, root, "metadata", 1, created_at
        )
    control_entry = _manifest_entry(control, root, "metadata", 1, created_at)
    members[control_entry["relative_path"]] = control_entry
    manifest["files"] = sorted(members.values(), key=lambda row: row["relative_path"])
    manifest["file_count"] = len(manifest["files"])
    manifest["compressed_bytes"] = sum(int(row["byte_count"]) for row in manifest["files"])
    manifest = reconcile_manifest_aggregate_counts(manifest)
    write_json_atomic(manifest_path, manifest)
    query_control = resolve_unpublished_control_path(successor_id)
    _copy_query_control(control, query_control)
    return {
        "successor_snapshot_id": successor_id, "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path), "state_path": str(state_path),
        "control_path": str(control), "query_control_path": str(query_control),
        "clone": clone,
        "source_rows": source_row_count, "fact_rows": fact_row_count,
        "new_locator_rows": len(locator_material),
        "control_delta": control_stats,
    }


def validate_staged_successor(
    context: FundUpdateContext,
    materialized: Mapping[str, Any],
    *,
    source_entries: Sequence[Mapping[str, Any]],
    fact_entries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate compact state and newly written members before head advancement.

    Inherited payloads remain proved by predecessor manifest membership and
    hard-link cloning, so validation never rescans the historical Fund body.
    """
    root = resolve_unpublished_snapshot_path(str(materialized["successor_snapshot_id"]))
    manifest_path = Path(str(materialized["manifest_path"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("predecessor_snapshot_id") != context.head.snapshot_id:
        raise FundUpdateError("successor manifest predecessor mismatch")
    members = {row["relative_path"]: row for row in manifest.get("files", [])}
    checked = 0
    for expected in list(source_entries) + list(fact_entries):
        member = members.get(expected["relative_path"])
        path = root / expected["relative_path"]
        if member is None or not path.is_file():
            raise FundUpdateError(f"new successor member is absent: {expected['relative_path']}")
        if member["content_sha256"] != expected["content_sha256"] or sha256_file(path) != expected["content_sha256"]:
            raise FundUpdateError(f"new successor member hash mismatch: {expected['relative_path']}")
        if int(member["row_count"]) != int(pq.ParquetFile(path).metadata.num_rows):
            raise FundUpdateError(f"new successor member row-count mismatch: {expected['relative_path']}")
        checked += 1
    control = Path(str(materialized["control_path"]))
    with closing(sqlite3.connect(control)) as connection:
        connection.row_factory = sqlite3.Row
        snapshot = connection.execute("SELECT snapshot_id FROM snapshot_catalog").fetchone()
        if not snapshot or snapshot[0] != materialized["successor_snapshot_id"]:
            raise FundUpdateError("successor control snapshot catalog mismatch")
        mixed_locators = connection.execute(
            "SELECT COUNT(*) FROM subject_partition_locator_registry WHERE snapshot_id<>?",
            (materialized["successor_snapshot_id"],),
        ).fetchone()[0]
        if mixed_locators:
            raise FundUpdateError("successor contains mixed-snapshot locators")
    query_control = Path(str(materialized["query_control_path"]))
    if not query_control.is_file() or sha256_file(query_control) != sha256_file(control):
        raise FundUpdateError("successor query control is absent or differs from snapshot control")
    view = _fund_control_view(str(materialized["successor_snapshot_id"]))
    with closing(sqlite3.connect(control)) as connection:
        connection.row_factory = sqlite3.Row
        orphan_relationships = sum(
            view.subject(str(row["from_type"]), str(row["from_id"])) is None
            or view.subject(str(row["to_type"]), str(row["to_id"])) is None
            for row in connection.execute("SELECT * FROM subject_relationship_registry")
        )
    if orphan_relationships:
        raise FundUpdateError("successor contains orphan subject relationships")
    return {
        "result": "PASS",
        "new_members_checked": checked,
        "orphan_relationships": 0,
        "mixed_snapshot_locators": 0,
        "inherited_bulk_payload_bytes_read": 0,
        "control_chain_depth": view.depth,
    }


def _normalize_exchange_refresh(sse: Sequence[Mapping[str, Any]], szse: Sequence[Mapping[str, Any]]) -> set[tuple[str, str]]:
    return {("SSE", str(row.get("FUND_CODE") or "").zfill(6)) for row in sse if row.get("FUND_CODE")} | {("SZSE", str(row.get("code") or "").zfill(6)) for row in szse if row.get("code")}


def run_user_triggered_fund_update(
    config: FundUpdateConfig,
    *,
    repository: ValidatedUpdateRepository | None = None,
    source_client: PublicFundSourceClient | None = None,
    run_id: str | None = None,
    writer_lease: InstallationWriterLease | None = None,
) -> dict[str, Any]:
    """Run one Fund update under the installation writer contract.

    The normal Update Data wrapper supplies a lease it keeps through
    publication.  Direct callers still receive cross-process exclusion for
    the update phase.
    """
    if writer_lease is not None:
        return _run_user_triggered_fund_update_locked(
            config, repository=repository, source_client=source_client,
            run_id=run_id, writer_lease=writer_lease,
        )
    selected_run_id = run_id or f"fund_update_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    lease = acquire_writer_lease(
        operation_id=selected_run_id,
        database_path=config.writer_control_path,
    )
    try:
        return _run_user_triggered_fund_update_locked(
            config, repository=repository, source_client=source_client,
            run_id=selected_run_id, writer_lease=lease,
        )
    except Exception:
        lease.release(status="failed")
        raise
    finally:
        if lease.record and lease.record.status == "active":
            lease.release()


def _run_user_triggered_fund_update_locked(
    config: FundUpdateConfig,
    *,
    repository: ValidatedUpdateRepository | None = None,
    source_client: PublicFundSourceClient | None = None,
    run_id: str | None = None,
    writer_lease: InstallationWriterLease | None = None,
) -> dict[str, Any]:
    if not UPDATE_LOCK.acquire(blocking=False):
        raise FundUpdateError("a China Public Fund update is already running")
    started = time.monotonic(); repository = repository or ValidatedUpdateRepository(); run_id = run_id or f"fund_update_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    identity_backup: Path | None = None
    head_advanced = False
    try:
        context = load_update_context(repository); run_root = config.output_root / "runs" / run_id; run_root.mkdir(parents=True, exist_ok=False)
        source = source_client or PublicFundSourceClient(
            run_root / "source", timeout=config.request_timeout_seconds,
            cache_search_root=config.output_root,
        )
        selected_families = set(config.selected_data_families or ("fund_nav", "listed_market_daily"))
        if not selected_families or selected_families - {"fund_nav", "listed_market_daily"}:
            raise FundUpdateError("unsupported selected Fund update family")
        nav_selected = "fund_nav" in selected_families
        listed_selected = "listed_market_daily" in selected_families
        latest_common = max(context.watermarks.values(), default=context.head.authoritative_cutoff)
        nav_watermarks = [
            value
            for (subject_type, _subject_id, metric), value in context.watermarks.items()
            if subject_type == "fund_share_class" and metric in NAV_METRICS
        ]
        latest_nav = max(nav_watermarks) if nav_watermarks else context.head.authoritative_cutoff
        start_date = (date.fromisoformat(latest_nav) + timedelta(days=1)).isoformat()
        # Exchange reality can be checked through the requested date while
        # regulator NAV acquisition stops at the latest completed day.
        nav_finish = min(date.fromisoformat(config.as_of_date), date.today() - timedelta(days=1))
        if writer_lease and writer_lease.record:
            write_runtime_owner_marker(
                run_root,
                operation_id=writer_lease.record.operation_id,
                owner_id=writer_lease.record.owner_id,
                predecessor_snapshot_id=context.head.snapshot_id,
                recovery_contract={
                    "kind": "china_public_fund_increment",
                    "logical_window_start": start_date,
                    "completed_through": nav_finish.isoformat(),
                    "disposal_proof": False,
                },
            )
        try:
            sse = source.sse_listings()
        except Exception as exc:
            is_population_failure = isinstance(exc, FundPopulationCompletenessError)
            receipts = list(source.calls)
            evidence = {
                "trigger": "user_intent_only",
                "predecessor_snapshot_id": context.head.snapshot_id,
                "incremental_start": start_date,
                "nav_incremental_end": nav_finish.isoformat(),
                "reality_refresh_as_of": config.as_of_date,
                "objects_checked": {
                    "accepted_share_classes": len(context.share_class_bindings),
                    "accepted_current_listings": len(context.listing_bindings),
                    "sse_rows": 0 if is_population_failure else None,
                    "szse_rows": None,
                },
                "refresh_complete": False,
                "no_change_eligible": False,
                "reality_delta": {
                    "new_listing_aliases": [], "identity_changes": [],
                    "termination_inference_from_absence": False,
                },
                "route_gaps": {
                    "sse_refresh": f"{type(exc).__name__}: {exc}",
                    "szse_refresh": "not_attempted_after_SSE_failure",
                    "listed_market_failures": [],
                },
                "szse_catalog_sessions": list(getattr(source, "catalog_sessions", [])),
                "population_completeness": {
                    "SSE_current_fund_list": (
                        "structurally_valid_but_untrustworthy_empty_population"
                        if is_population_failure else "malformed_or_incomplete_source_contract"
                    )
                },
            }
            write_json_atomic(
                run_root / "discovery_and_acquisition_v1.json",
                {**evidence, "source_receipts": receipts},
            )
            result_name = (
                "untrustworthy_authoritative_refresh"
                if is_population_failure else "incomplete_authoritative_refresh"
            )
            result = {
                "schema_version": "fr_china_public_fund_user_update_result_v1",
                "run_id": run_id, "result": result_name,
                "predecessor_snapshot_id": context.head.snapshot_id,
                "successor_snapshot_id": None, "head_advanced": False,
                "duration_seconds": round(time.monotonic() - started, 3),
                "source_calls": len(receipts),
                "incomplete_routes": ["SSE_current_fund_list"],
            }
            write_json_atomic(run_root / "result_v1.json", result)
            if writer_lease and writer_lease.record:
                write_runtime_owner_marker(run_root, operation_id=writer_lease.record.operation_id, owner_id=writer_lease.record.owner_id, predecessor_snapshot_id=context.head.snapshot_id, state="completed")
            return result
        try:
            szse = source.szse_listings()
        except Exception as exc:
            szse_error = f"{type(exc).__name__}: {exc}"
            receipts = list(source.calls)
            evidence = {
                "trigger": "user_intent_only",
                "predecessor_snapshot_id": context.head.snapshot_id,
                "incremental_start": start_date,
                "nav_incremental_end": nav_finish.isoformat(),
                "reality_refresh_as_of": config.as_of_date,
                "objects_checked": {
                    "accepted_share_classes": len(context.share_class_bindings),
                    "accepted_current_listings": len(context.listing_bindings),
                    "sse_rows": len(sse),
                    "szse_rows": None,
                },
                "refresh_complete": False,
                "no_change_eligible": False,
                "reality_delta": {
                    "new_listing_aliases": [], "identity_changes": [],
                    "termination_inference_from_absence": False,
                },
                "route_gaps": {"szse_refresh": szse_error, "listed_market_failures": []},
                "szse_catalog_sessions": list(getattr(source, "catalog_sessions", [])),
            }
            write_json_atomic(
                run_root / "discovery_and_acquisition_v1.json",
                {**evidence, "source_receipts": receipts},
            )
            result = {
                "schema_version": "fr_china_public_fund_user_update_result_v1",
                "run_id": run_id,
                "result": "incomplete_authoritative_refresh",
                "predecessor_snapshot_id": context.head.snapshot_id,
                "successor_snapshot_id": None,
                "head_advanced": False,
                "duration_seconds": round(time.monotonic() - started, 3),
                "source_calls": len(receipts),
                "incomplete_routes": ["SZSE_current_fund_list"],
            }
            write_json_atomic(run_root / "result_v1.json", result)
            if writer_lease and writer_lease.record:
                write_runtime_owner_marker(run_root, operation_id=writer_lease.record.operation_id, owner_id=writer_lease.record.owner_id, predecessor_snapshot_id=context.head.snapshot_id, state="completed")
            return result
        szse_error = None
        observed_listings = _normalize_exchange_refresh(sse, szse)
        known_listings = set(context.listing_bindings)
        new_listings = sorted(observed_listings - known_listings)
        if new_listings:
            context, identity_backup = onboard_new_exchange_listings(
                context, source, sse, szse, new_listings
            )
            known_listings = set(context.listing_bindings)
        stage_root = run_root / "staged_increment"
        context, identity_backup, recovered = (
            recover_staged_increment(
                context, config.output_root, stage_root,
                start_date=start_date, completed_through=nav_finish.isoformat(),
                existing_backup=identity_backup,
            ) if nav_selected else (context, identity_backup, None)
        )
        source_entries: list[dict[str, Any]] = list(recovered["source_entries"]) if recovered else []
        fact_entries: list[dict[str, Any]] = list(recovered["fact_entries"]) if recovered else []
        locator_material: list[dict[str, Any]] = list(recovered["locator_material"]) if recovered else []
        source_row_count = int(recovered["source_row_count"]) if recovered else 0
        fact_row_count = int(recovered["fact_row_count"]) if recovered else 0
        unknown_pairs: set[tuple[str, str]] = set(); empty_values = 0
        conflict_count = 0; conflict_examples: list[dict[str, Any]] = []
        cursor = date.fromisoformat(start_date); finish = nav_finish
        if not nav_selected:
            cursor = finish + timedelta(days=1)
        cached_recovery: dict[str, Any] | None = None
        if recovered:
            new_listing_pairs = {
                (str(change["csrc_eid_fund_id"]), str(change["code"]).zfill(6))
                for change in context.identity_changes
                if change.get("change_type") == "new_exchange_listed_fund_object_graph"
            }
            recovered_rows, cached_recovery = load_cached_unknown_valuation_rows(
                context, config.output_root, start_date=start_date,
                end_date=nav_finish.isoformat(), include_pairs=new_listing_pairs,
            )
            if cached_recovery.get("result") == "unavailable":
                raise FundUpdateError(
                    "failed increment cannot be resumed because retained authoritative response coverage is incomplete"
                )
            context, identity_backup, recovered_pairs = onboard_new_csrc_share_classes(
                context, source, recovered_rows, existing_backup=identity_backup
            )
            recovered_sources, recovered_facts, recovered_resolution = build_incremental_rows(
                context, recovered_rows, {}, processed_at=utc_now()
            )
            if recovered_sources:
                entries, _ = _write_parquet_groups(stage_root, "source_observations", recovered_sources, f"{run_id}_recovered_new_classes", utc_now()); source_entries.extend(entries)
                entries, locators = _write_parquet_groups(stage_root, "standard_facts", recovered_facts, f"{run_id}_recovered_new_classes", utc_now()); fact_entries.extend(entries); locator_material.extend(locators)
                source_row_count += len(recovered_sources); fact_row_count += len(recovered_facts)
            unknown_pairs.update(tuple(row) for row in recovered_resolution["unknown_share_class_pairs"])
            empty_values += int(recovered_resolution["empty_metric_values"])
            conflict_count += int(recovered_resolution["conflicting_logical_fact_count"])
            conflict_examples.extend(recovered_resolution["conflict_examples"])
            conflict_count += int(recovered.get("conflicting_logical_fact_count", 0))
            conflict_examples.extend(recovered.get("conflict_examples", []))
            cached_recovery["new_share_class_pairs_onboarded"] = len(recovered_pairs)
            cursor = finish + timedelta(days=1)
        while cursor <= finish:
            day = cursor.isoformat()
            valuations = source.csrc_valuations(day, day)
            context, identity_backup, _new_pairs = onboard_new_csrc_share_classes(
                context, source, valuations, existing_backup=identity_backup
            )
            needed_series = []
            for item in valuations:
                fund_id = str((item.get("fund") or {}).get("idStr") or "")
                code = str(item.get("code") or "").zfill(6)
                binding = context.share_class_bindings.get((fund_id, code))
                if binding:
                    for metric, field in (("fund.nav", "shareNetValue"), ("fund.accumulated_nav", "totalNetValue")):
                        if item.get(field) not in (None, ""):
                            needed_series.append(("fund_share_class", binding["subject_id"], metric))
            context, identity_backup = ensure_incremental_series(
                context, needed_series, existing_backup=identity_backup
            )
            day_sources, day_facts, day_resolution = build_incremental_rows(
                context, valuations, {}, processed_at=utc_now()
            )
            if day_sources:
                entries, _ = _write_parquet_groups(stage_root, "source_observations", day_sources, f"{run_id}_{day}", utc_now()); source_entries.extend(entries)
                entries, locators = _write_parquet_groups(stage_root, "standard_facts", day_facts, f"{run_id}_{day}", utc_now()); fact_entries.extend(entries); locator_material.extend(locators)
                source_row_count += len(day_sources); fact_row_count += len(day_facts)
            unknown_pairs.update(tuple(row) for row in day_resolution["unknown_share_class_pairs"])
            empty_values += int(day_resolution["empty_metric_values"])
            conflict_count += int(day_resolution["conflicting_logical_fact_count"])
            conflict_examples.extend(day_resolution["conflict_examples"])
            write_json_atomic(run_root / "acquisition_checkpoint_v1.json", {
                "run_id": run_id, "last_completed_date": day,
                "source_observations_staged": source_row_count,
                "standard_facts_staged": fact_row_count,
                "source_calls_completed": len(source.calls),
            })
            cursor += timedelta(days=1)
        market_rows: dict[tuple[str, str], Sequence[Sequence[str]]] = {}
        failures: list[dict[str, Any]] = []
        def fetch_listing(key: tuple[str, str]) -> tuple[tuple[str, str], list[list[str]]]:
            venue, code = key; latest = max(context.watermarks.get(("listing", context.listing_bindings[key]["subject_id"], metric), latest_common) for metric in LISTED_METRICS)
            calendar_days = (date.fromisoformat(config.as_of_date) - date.fromisoformat(latest)).days + config.tencent_overlap_calendar_days
            return key, source.tencent_kline(venue, code, max(20, min(160, calendar_days * 2)))
        if listed_selected:
            with ThreadPoolExecutor(max_workers=config.source_workers) as executor:
                futures = {executor.submit(fetch_listing, key): key for key in sorted(known_listings)}
                for future in as_completed(futures):
                    try: key, rows = future.result(); market_rows[key] = rows
                    except Exception as exc: failures.append({"venue": futures[future][0], "code": futures[future][1], "error": f"{type(exc).__name__}: {exc}"})
        market_targets = [
            ("listing", context.listing_bindings[key]["subject_id"], metric)
            for key in market_rows for metric in LISTED_METRICS
        ]
        context, identity_backup = ensure_incremental_series(
            context, market_targets, existing_backup=identity_backup
        )
        market_sources, market_facts, market_resolution = build_incremental_rows(context, [], market_rows, processed_at=utc_now())
        if market_sources:
            entries, _ = _write_parquet_groups(stage_root, "source_observations", market_sources, f"{run_id}_listed", utc_now()); source_entries.extend(entries)
            entries, locators = _write_parquet_groups(stage_root, "standard_facts", market_facts, f"{run_id}_listed", utc_now()); fact_entries.extend(entries); locator_material.extend(locators)
            source_row_count += len(market_sources); fact_row_count += len(market_facts)
        unknown_pairs.update(tuple(row) for row in market_resolution["unknown_share_class_pairs"])
        empty_values += int(market_resolution["empty_metric_values"])
        conflict_count += int(market_resolution["conflicting_logical_fact_count"])
        conflict_examples.extend(market_resolution["conflict_examples"])
        resolution = {
            "unknown_share_class_pairs": sorted(unknown_pairs),
            "unknown_share_class_pair_count": len(unknown_pairs),
            "empty_metric_values": empty_values,
            "conflicting_logical_fact_count": conflict_count,
            "conflict_examples": conflict_examples[:20],
            "conflict_treatment": "retain distinct source observations; do not promote a contradictory standard fact",
        }
        if resolution["unknown_share_class_pair_count"]:
            raise FundIdentityReviewRequired(f"CSRC refresh discovered {resolution['unknown_share_class_pair_count']} share-class identities not present in accepted Fund state")
        receipts = list(source.calls)
        recovery_evidence = None if recovered is None else {
            key: value for key, value in recovered.items()
            if key not in {"source_entries", "fact_entries", "locator_material"}
        }
        refresh_complete = not failures
        evidence = {"trigger": "user_intent_only", "predecessor_snapshot_id": context.head.snapshot_id, "incremental_start": start_date, "nav_incremental_end": nav_finish.isoformat(), "reality_refresh_as_of": config.as_of_date, "objects_checked": {"accepted_share_classes": len(context.share_class_bindings), "accepted_current_listings": len(context.listing_bindings), "sse_rows": len(sse), "szse_rows": len(szse)}, "refresh_complete": refresh_complete, "no_change_eligible": refresh_complete, "reality_delta": {"new_listing_aliases": new_listings, "identity_changes": list(context.identity_changes), "termination_inference_from_absence": False}, "route_gaps": {"szse_refresh": szse_error, "listed_market_failures": failures}, "szse_catalog_sessions": list(getattr(source, "catalog_sessions", [])), "observation_resolution": resolution, "failed_run_recovery": recovery_evidence, "retained_authoritative_response_recovery": cached_recovery}
        write_json_atomic(run_root / "discovery_and_acquisition_v1.json", {**evidence, "source_receipts": receipts})
        if config.failpoint == "before_materialization": raise FundUpdateError("injected failure before materialization")
        if not source_row_count and not context.identity_changes:
            result_name = "no_material_change" if refresh_complete else "incomplete_source_refresh"
            result = {"schema_version": "fr_china_public_fund_user_update_result_v1", "run_id": run_id, "result": result_name, "predecessor_snapshot_id": context.head.snapshot_id, "successor_snapshot_id": None, "head_advanced": False, "duration_seconds": round(time.monotonic() - started, 3), "source_calls": len(receipts), "refresh_complete": refresh_complete, "incomplete_listing_routes": failures}
            write_json_atomic(run_root / "result_v1.json", result)
            if writer_lease and writer_lease.record:
                write_runtime_owner_marker(
                    run_root,
                    operation_id=writer_lease.record.operation_id,
                    owner_id=writer_lease.record.owner_id,
                    predecessor_snapshot_id=context.head.snapshot_id,
                    state="completed",
                    recovery_contract=terminal_disposal_contract()
                    if result_name == "no_material_change" else None,
                )
            return result
        materialized = materialize_staged_successor(
            context, config, run_id=run_id, stage_root=stage_root,
            source_entries=source_entries, fact_entries=fact_entries,
            locator_material=locator_material,
            source_row_count=source_row_count, fact_row_count=fact_row_count,
            reality_evidence=evidence, source_receipts=receipts,
        )
        pre_cas_validation = validate_staged_successor(
            context,
            materialized,
            source_entries=source_entries,
            fact_entries=fact_entries,
        )
        if config.failpoint == "before_cas": raise FundUpdateError("injected failure before CAS")
        root = resolve_unpublished_snapshot_path(materialized["successor_snapshot_id"]); reality = root / FUND_REALITY; state = root / FUND_STATE
        candidate = ValidatedUpdateHead(universe=UNIVERSE, database_generation_id=context.head.database_generation_id, snapshot_id=materialized["successor_snapshot_id"], snapshot_manifest_sha256=materialized["manifest_sha256"], reality_owner_path=str(reality), reality_owner_sha256=sha256_file(reality), state_path=str(state), state_sha256=sha256_file(state), authoritative_cutoff=config.as_of_date, predecessor_snapshot_id=context.head.snapshot_id, transaction_id=materialized["successor_snapshot_id"], run_id=run_id)
        repository.compare_and_swap(context.head.snapshot_id, candidate)
        head_advanced = True
        result = {"schema_version": "fr_china_public_fund_user_update_result_v1", "run_id": run_id, "result": "success" if refresh_complete else "success_with_source_gaps", "predecessor_snapshot_id": context.head.snapshot_id, "successor_snapshot_id": candidate.snapshot_id, "head_advanced": True, "source_calls": len(receipts), "source_observations": source_row_count, "standard_facts": fact_row_count, "listed_route_failures": len(failures), "refresh_complete": refresh_complete, "duration_seconds": round(time.monotonic() - started, 3), "active_pointer_unchanged": True, "pre_cas_validation": pre_cas_validation, **materialized}
        write_json_atomic(run_root / "result_v1.json", result)
        if writer_lease and writer_lease.record:
            # The whole workflow still owns publication.  Keep the marker
            # active with the successor named so a crash between head CAS and
            # publication is recoverable rather than mistaken for disposable
            # completed work.
            write_runtime_owner_marker(run_root, operation_id=writer_lease.record.operation_id, owner_id=writer_lease.record.owner_id, predecessor_snapshot_id=context.head.snapshot_id, state="active", successor_snapshot_id=candidate.snapshot_id, checkpoint_verified=True)
        return result
    except Exception:
        # A failed run remains on disk for recovery/diagnosis.  It is never
        # silently deleted by the update path.
        if writer_lease and writer_lease.record:
            try:
                write_runtime_owner_marker(run_root, operation_id=writer_lease.record.operation_id, owner_id=writer_lease.record.owner_id, predecessor_snapshot_id=locals().get("context").head.snapshot_id if locals().get("context") else None, state="failed", successor_snapshot_id=None)
            except Exception:
                pass
        if identity_backup is not None and not head_advanced:
            InstallationIdentityState.recover_from_backup(
                resolve_identity_state_path(), resolve_identity_state_backup_root(), identity_backup
            )
        raise
    finally:
        UPDATE_LOCK.release()


def reconcile_user_update_metadata(
    repository: ValidatedUpdateRepository | None = None,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Create a metadata-only child when final update summaries need repair.

    This never reads inherited Fund payloads.  It derives object deltas from
    the two compact control databases and conflict treatment from only the
    incremental files introduced by the user-triggered update.
    """
    repository = repository or ValidatedUpdateRepository()
    head = repository.current(UNIVERSE)
    if head is None or not head.predecessor_snapshot_id:
        raise FundUpdateError("Fund update head has no predecessor to reconcile")
    current_root = resolve_unpublished_snapshot_path(head.snapshot_id)
    predecessor_root = resolve_unpublished_snapshot_path(head.predecessor_snapshot_id)
    current_manifest = json.loads((current_root / MANIFEST).read_text(encoding="utf-8"))
    predecessor_manifest = json.loads((predecessor_root / MANIFEST).read_text(encoding="utf-8"))
    predecessor_members = {row["relative_path"] for row in predecessor_manifest["files"]}

    current_keys = {
        (str(row["subject_type"]), str(row["subject_id"]))
        for row in _fund_control_view(head.snapshot_id).subjects()
    }
    predecessor_keys = {
        (str(row["subject_type"]), str(row["subject_id"]))
        for row in _fund_control_view(head.predecessor_snapshot_id).subjects()
    }
    new_keys = current_keys - predecessor_keys
    type_deltas = {
        subject_type: sum(row_type == subject_type for row_type, _subject_id in new_keys)
        for subject_type in ("fund", "fund_share_class", "instrument", "listing", "series")
    }

    current_state = json.loads((current_root / FUND_STATE).read_text(encoding="utf-8"))
    new_source_entries = [
        row for row in current_manifest["files"]
        if row["relative_path"] not in predecessor_members
        and row["layer_name"] == "source_observations"
    ]
    new_fact_entries = [
        row for row in current_manifest["files"]
        if row["relative_path"] not in predecessor_members
        and row["layer_name"] == "standard_facts"
    ]
    source_values: dict[tuple[str, str, str], set[str]] = {}
    for entry in new_source_entries:
        table = pq.ParquetFile(current_root / entry["relative_path"]).read(
            columns=["entity_key", "metric_id", "event_date_or_period", "raw_value_json"]
        )
        for row in table.to_pylist():
            coordinate = (
                str(row["entity_key"]), str(row["metric_id"]),
                str(row["event_date_or_period"]),
            )
            source_values.setdefault(coordinate, set()).add(str(row["raw_value_json"]))
    conflict_coordinates = {
        coordinate for coordinate, values in source_values.items() if len(values) > 1
    }
    promoted_conflicts: set[tuple[str, str, str]] = set()
    for entry in new_fact_entries:
        parquet = pq.ParquetFile(current_root / entry["relative_path"])
        for batch in parquet.iter_batches(
            columns=["subject_id", "metric_id", "economic_time"], batch_size=50_000
        ):
            for row in batch.to_pylist():
                coordinate = (
                    str(row["subject_id"]), str(row["metric_id"]),
                    str(row["economic_time"]),
                )
                if coordinate in conflict_coordinates:
                    promoted_conflicts.add(coordinate)
    if promoted_conflicts:
        raise FundUpdateError("contradictory incremental sources have promoted facts")

    created_at = utc_now()
    run_id = run_id or f"fund_update_metadata_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    digest = hashlib.sha256(canonical_json({
        "predecessor": head.snapshot_id,
        "type_deltas": type_deltas,
        "conflicts": len(conflict_coordinates),
    }).encode()).hexdigest()[:12]
    successor_id = f"frfundupdatemeta1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{digest}"
    clone = clone_snapshot_from_manifest(head.snapshot_id, successor_id)
    root = resolve_unpublished_snapshot_path(successor_id)
    shutil.copy2(current_root / MANIFEST, root / MANIFEST)
    control = root / FUND_CONTROL
    metadata_context = FundUpdateContext(
        head=head, predecessor_root=current_root,
        control_path=current_root / FUND_CONTROL,
        watermarks={}, share_class_bindings={}, listing_bindings={}, series_bindings={},
    )
    control_stats = _write_incremental_control(
        metadata_context, control, successor_id=successor_id,
        created_at=created_at,
        manifest_entries=[
            row for row in current_manifest["files"]
            if row["layer_name"] in {"source_observations", "standard_facts"}
        ],
        locator_material=[],
    )

    evidence_path = root / "metadata/china_public_fund/update_reality_and_source_evidence_v1.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    retained_resolution = dict(evidence.get("observation_resolution") or {})
    reported_type_deltas = dict(
        (evidence.get("metadata_reconciliation") or {}).get(
            "subject_type_deltas_from_accepted_predecessor"
        ) or type_deltas
    )
    examples = [
        {
            "subject_id": subject_id, "metric_id": metric_id,
            "economic_date": economic_date,
            "values": sorted(source_values[(subject_id, metric_id, economic_date)]),
        }
        for subject_id, metric_id, economic_date in sorted(conflict_coordinates)[:20]
    ]
    if new_source_entries:
        evidence["observation_resolution"].update({
            "conflicting_logical_fact_count": len(conflict_coordinates),
            "conflict_examples": examples,
            "promoted_conflicting_fact_count": 0,
            "conflict_count_basis": "recomputed from successor-only Source Observations",
        })
    else:
        evidence["observation_resolution"] = retained_resolution
    evidence["metadata_reconciliation"] = {
        "predecessor_update_snapshot_id": head.snapshot_id,
        "subject_type_deltas_from_accepted_predecessor": reported_type_deltas,
        "business_payload_members_changed": 0,
    }
    write_json_atomic(evidence_path, evidence)

    predecessor_reality = json.loads((predecessor_root / FUND_REALITY).read_text(encoding="utf-8"))
    reality_path = root / FUND_REALITY
    reality = json.loads(reality_path.read_text(encoding="utf-8"))
    expected_counts = (
        {
            "fund_products": sum(subject_type == "fund" for subject_type, _ in current_keys),
            "fund_share_classes": sum(subject_type == "fund_share_class" for subject_type, _ in current_keys),
            "current_exchange_listings": int(reality["current_exchange_listings"]),
        }
        if current_state.get("metadata_only_reconciliation")
        else {
            "fund_products": sum(subject_type == "fund" for subject_type, _ in current_keys),
            "fund_share_classes": sum(subject_type == "fund_share_class" for subject_type, _ in current_keys),
            "current_exchange_listings": int(predecessor_reality["current_exchange_listings"]) + type_deltas["listing"],
        }
    )
    reality.update({
        **expected_counts,
        "last_user_triggered_update_evidence": evidence_path.relative_to(root).as_posix(),
        "last_user_triggered_update_evidence_sha256": sha256_file(evidence_path),
    })
    write_json_atomic(reality_path, reality)

    identity_owner_path = root / FUND_IDENTITY
    identity_owner = json.loads(identity_owner_path.read_text(encoding="utf-8"))
    identity_owner["control_sha256"] = sha256_file(control)
    write_json_atomic(identity_owner_path, identity_owner)
    state_path = root / FUND_STATE
    state = json.loads(state_path.read_text(encoding="utf-8"))
    query_contract_path = root / "metadata/china_public_fund/query_contract_v1.json"
    query_contract = json.loads(query_contract_path.read_text(encoding="utf-8"))
    query_contract["snapshot_id"] = successor_id
    write_json_atomic(query_contract_path, query_contract)
    state.update({
        "schema_version": "fr_china_public_fund_validated_update_state_v3",
        "snapshot_id": successor_id,
        "predecessor_snapshot_id": head.snapshot_id,
        "successor_snapshot_id": successor_id,
        "run_id": run_id,
        "control_owner_path": str(control),
        "control_owner_sha256": sha256_file(control),
        "identity_owner_path": str(identity_owner_path),
        "identity_owner_sha256": sha256_file(identity_owner_path),
        "query_contract_path": str(root / "metadata/china_public_fund/query_contract_v1.json"),
        "query_contract_sha256": sha256_file(query_contract_path),
        "metadata_only_reconciliation": True,
    })
    write_json_atomic(state_path, state)

    manifest_path = root / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    members = {row["relative_path"]: dict(row) for row in manifest["files"]}
    for path in (
        control, evidence_path, reality_path, identity_owner_path, state_path,
        query_contract_path,
    ):
        members[path.relative_to(root).as_posix()] = _manifest_entry(
            path, root, "metadata", 1, created_at
        )
    manifest.update({
        "snapshot_id": successor_id,
        "predecessor_snapshot_id": head.snapshot_id,
        "predecessor_manifest_sha256": head.snapshot_manifest_sha256,
        "run_id": run_id,
        "created_at_utc": created_at,
    })
    manifest["files"] = sorted(members.values(), key=lambda row: row["relative_path"])
    manifest["file_count"] = len(manifest["files"])
    manifest["compressed_bytes"] = sum(int(row["byte_count"]) for row in manifest["files"])
    manifest = reconcile_manifest_aggregate_counts(manifest)
    write_json_atomic(manifest_path, manifest)
    query_control = resolve_unpublished_control_path(successor_id)
    _copy_query_control(control, query_control)

    current_business = {
        row["relative_path"]: (row["row_count"], row["byte_count"], row["content_sha256"])
        for row in current_manifest["files"] if row["layer_name"] in {"source_observations", "standard_facts"}
    }
    successor_business = {
        row["relative_path"]: (row["row_count"], row["byte_count"], row["content_sha256"])
        for row in manifest["files"] if row["layer_name"] in {"source_observations", "standard_facts"}
    }
    if current_business != successor_business:
        raise FundUpdateError("metadata reconciliation changed business payload inventory")
    with closing(sqlite3.connect(control)) as connection:
        mixed = connection.execute(
            "SELECT COUNT(*) FROM subject_partition_locator_registry WHERE snapshot_id<>?",
            (successor_id,),
        ).fetchone()[0]
    if mixed:
        raise FundUpdateError("metadata reconciliation contains mixed-snapshot locators")
    if sha256_file(query_control) != sha256_file(control):
        raise FundUpdateError("metadata reconciliation query control differs from snapshot control")

    candidate = ValidatedUpdateHead(
        universe=UNIVERSE,
        database_generation_id=head.database_generation_id,
        snapshot_id=successor_id,
        snapshot_manifest_sha256=sha256_file(manifest_path),
        reality_owner_path=str(reality_path),
        reality_owner_sha256=sha256_file(reality_path),
        state_path=str(state_path), state_sha256=sha256_file(state_path),
        authoritative_cutoff=head.authoritative_cutoff,
        predecessor_snapshot_id=head.snapshot_id,
        transaction_id=successor_id, run_id=run_id,
    )
    repository.compare_and_swap(head.snapshot_id, candidate)
    return {
        "result": "success", "metadata_only": True,
        "predecessor_snapshot_id": head.snapshot_id,
        "successor_snapshot_id": successor_id,
        "manifest_sha256": candidate.snapshot_manifest_sha256,
        "subject_type_deltas": type_deltas,
        "conflicting_logical_fact_count": len(conflict_coordinates),
        "promoted_conflicting_fact_count": 0,
        "business_payload_members_changed": 0,
        "clone": clone,
        "control_delta": control_stats,
    }


def update_state(repository: ValidatedUpdateRepository | None = None) -> dict[str, Any]:
    repository = repository or ValidatedUpdateRepository(); head = repository.current(UNIVERSE)
    return {"universe": "Fund", "jurisdiction": "CN", "operation": "Update China Public Fund", "running": UPDATE_LOCK.locked(), "validated_head": asdict(head) if head else None, "background_scheduler": False, "active_pointer": json.loads(resolve_active_snapshot_pointer().read_text(encoding="utf-8")) if resolve_active_snapshot_pointer().is_file() else None}
    resolve_identity_state_backup_root,
