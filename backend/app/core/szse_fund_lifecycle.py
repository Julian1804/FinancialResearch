"""Authoritative SZSE listed-Fund lifecycle discovery and reconciliation.

The Shenzhen Stock Exchange Fund notice channel is the authority used here for
listing and termination effective dates.  Search responses discover candidate
documents only.  Promotion always parses the complete official JSON document,
retains its exact bytes, and binds the extracted event to that document hash.

This module deliberately does not infer lifecycle from market observations,
NAV history, Fund contract dates, names, or current-population membership.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableSequence, Sequence

import requests
from pypdf import PdfReader

from backend.app.core.artifact_io import canonical_json
from backend.app.core.source_transport import append_response_receipt, retain_bytes_once, sha256_bytes


SEARCH_URL = "https://www.szse.cn/api/search/content"
NOTICE_REFERER = "https://www.szse.cn/disclosure/notice/fund/index.html"
NOTICE_ORIGIN = "https://www.szse.cn"
CHANNEL = "fund_news"
SCHEMA_VERSION = "fr_szse_fund_listing_lifecycle_episode_v1"
SZSE_TIMEZONE = timezone(timedelta(hours=8))


class SZSEFundLifecycleError(RuntimeError):
    pass


class SZSEFundLifecycleSourceError(SZSEFundLifecycleError):
    pass


class SZSEFundLifecycleUnresolved(SZSEFundLifecycleError):
    """Authoritative evidence is absent, conflicting, or ambiguous."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return re.sub(r"\s+", "", html.unescape("".join(parser.parts)))


def _iso_date(year: str, month: str, day: str) -> str:
    return date(int(year), int(month), int(day)).isoformat()


_DATE = r"(?P<year>20\d{2})\s*年\s*(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
_CODE_PATTERNS = (
    re.compile(r"(?:证券|基金|交易)代码[：:，,为“\"']*(?P<code>\d{6})"),
    re.compile(r"代码[（(]?(?P<code>\d{6})[）)]?"),
)
_START_PATTERNS = (
    re.compile(rf"自{_DATE}起?在本所上市交易"),
    re.compile(rf"于{_DATE}在本所上市交易"),
    re.compile(rf"{_DATE}(?:起|开始)在(?:本所|我所)上市交易"),
    re.compile(rf"上市(?:交易)?(?:日|日期)[：:]?{_DATE}"),
)
_END_PATTERNS = (
    re.compile(rf"自{_DATE}(?:起)?终止上市(?:交易)?"),
    re.compile(rf"终止上市(?:交易)?(?:日|日期)[：:]?{_DATE}"),
)


def _fund_kind(text: str) -> str | None:
    if "基础设施证券投资基金" in text:
        return "public_reit"
    if "交易型开放式" in text:
        return "etf"
    if "LOF" in text.upper() or "上市开放式" in text:
        return "lof"
    return None


def _codes(text: str) -> set[str]:
    result: set[str] = set()
    for pattern in _CODE_PATTERNS:
        result.update(match.group("code") for match in pattern.finditer(text))
    return result


def _dates(patterns: Sequence[re.Pattern[str]], text: str) -> set[str]:
    return {
        _iso_date(match.group("year"), match.group("month"), match.group("day"))
        for pattern in patterns
        for match in pattern.finditer(text)
    }


def _publication_date(milliseconds: Any) -> str:
    try:
        value = int(milliseconds)
    except (TypeError, ValueError) as exc:
        raise SZSEFundLifecycleSourceError("SZSE notice lacks a valid publication timestamp") from exc
    return datetime.fromtimestamp(value / 1000, SZSE_TIMEZONE).date().isoformat()


def _safe_segment(value: str) -> str:
    if not value or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError("retained source identifier must be one safe path segment")
    return value


@dataclass(frozen=True)
class LifecycleEvent:
    event_type: str
    code: str
    effective_date: str
    fund_kind: str
    fund_name: str
    document_id: str
    publication_date: str
    document_url: str
    document_json_url: str
    document_sha256: str
    retained_response_file: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def parse_official_notice(
    payload: Mapping[str, Any],
    *,
    document_sha256: str,
    retained_response_file: str,
    requested_code: str | None = None,
    requested_kind: str | None = None,
) -> list[LifecycleEvent]:
    """Extract authoritative events from one complete official document.

    A document with multiple effective dates for the same event is rejected.
    Multiple codes may share one event date, but a requested-code lookup only
    returns that exact code.  Names and codes remain evidence; they do not
    allocate an FR identity.
    """
    data = payload.get("data")
    if payload.get("code") != 0 or not isinstance(data, Mapping):
        raise SZSEFundLifecycleSourceError("SZSE notice JSON is not a successful document envelope")
    if data.get("chnlCode") != CHANNEL:
        raise SZSEFundLifecycleSourceError("SZSE lifecycle document is outside the Fund notice channel")
    title = str(data.get("title") or "").strip()
    content = str(data.get("content") or "")
    text = _plain_text(title + content)
    if requested_kind not in {None, "etf", "lof", "public_reit"}:
        raise ValueError("unsupported SZSE Fund classification hint")
    kind = _fund_kind(text) or requested_kind
    if kind is None:
        return []
    codes = _codes(text)
    if requested_code is not None:
        if requested_code not in codes:
            return []
        codes = {requested_code}
    starts = _dates(_START_PATTERNS, text)
    ends = _dates(_END_PATTERNS, text)
    if len(starts) > 1 or len(ends) > 1:
        raise SZSEFundLifecycleUnresolved(
            f"SZSE document {data.get('docId')} contains conflicting lifecycle dates"
        )
    if not starts and not ends:
        return []
    if not codes:
        raise SZSEFundLifecycleUnresolved(
            f"SZSE lifecycle document {data.get('docId')} has no bindable six-digit code"
        )
    json_path = str(data.get("jsonPath") or "")
    html_path = str(data.get("url") or "")
    if not json_path.startswith("/") or not html_path.startswith("/"):
        raise SZSEFundLifecycleSourceError("SZSE notice paths are not official site-relative paths")
    name = re.sub(
        r"^(?:关于)?|(?:上市交易|终止上市交易|终止上市)(?:的)?(?:公告|通知)$",
        "",
        title,
    ).strip()
    publication_date = _publication_date(data.get("pubTime"))
    events: list[LifecycleEvent] = []
    for code in sorted(codes):
        for event_type, values in (("listing_start", starts), ("listing_end", ends)):
            for effective_date in values:
                events.append(
                    LifecycleEvent(
                        event_type=event_type,
                        code=code,
                        effective_date=effective_date,
                        fund_kind=kind,
                        fund_name=name,
                        document_id=str(data.get("docId")),
                        publication_date=publication_date,
                        document_url=NOTICE_ORIGIN + html_path,
                        document_json_url=NOTICE_ORIGIN + json_path,
                        document_sha256=document_sha256,
                        retained_response_file=retained_response_file,
                    )
                )
    return events


def reconcile_code_lifecycle(
    code: str,
    events: Iterable[LifecycleEvent],
    *,
    require_current_episode: bool,
) -> list[dict[str, Any]]:
    """Build non-overlapping listing episodes or refuse ambiguous evidence."""
    code = str(code).zfill(6)
    selected = [event for event in events if event.code == code]
    by_coordinate: dict[tuple[str, str], list[LifecycleEvent]] = {}
    for event in selected:
        by_coordinate.setdefault((event.event_type, event.effective_date), []).append(event)
    starts = sorted(day for event_type, day in by_coordinate if event_type == "listing_start")
    ends = sorted(day for event_type, day in by_coordinate if event_type == "listing_end")
    if not starts:
        raise SZSEFundLifecycleUnresolved(f"SZSE {code} has no authoritative listing-start document")
    kinds = {event.fund_kind for event in selected}
    if len(kinds) != 1:
        raise SZSEFundLifecycleUnresolved(f"SZSE {code} has conflicting official Fund classifications")
    assignments: list[tuple[str, str | None]] = []
    unused_ends = list(ends)
    for position, start in enumerate(starts):
        next_start = starts[position + 1] if position + 1 < len(starts) else None
        candidates = [end for end in unused_ends if end >= start and (next_start is None or end < next_start)]
        if next_start is not None and len(candidates) != 1:
            raise SZSEFundLifecycleUnresolved(
                f"SZSE {code} listing start {start} is not uniquely closed before later start {next_start}"
            )
        if next_start is None and len(candidates) > 1:
            raise SZSEFundLifecycleUnresolved(
                f"SZSE {code} has multiple termination dates for its final listing episode"
            )
        end = candidates[0] if candidates else None
        if end is not None:
            unused_ends.remove(end)
        assignments.append((start, end))
    if unused_ends:
        raise SZSEFundLifecycleUnresolved(
            f"SZSE {code} has orphan or unassignable termination evidence"
        )

    episodes: list[dict[str, Any]] = []
    for start, end in assignments:
        start_evidence = [event.as_dict() for event in by_coordinate[("listing_start", start)]]
        end_evidence = [event.as_dict() for event in by_coordinate.get(("listing_end", end), [])] if end else []
        material = {
            "venue": "SZSE",
            "code": code,
            "fund_kind": next(iter(kinds)),
            "listing_start_date": start,
            "listing_end_date": end,
            "start_document_sha256": sorted(row["document_sha256"] for row in start_evidence),
            "end_document_sha256": sorted(row["document_sha256"] for row in end_evidence),
        }
        episodes.append(
            {
                "schema_version": SCHEMA_VERSION,
                **material,
                "lifecycle_status": "ended" if end else "current",
                "lifecycle_date_roles": {
                    "listing_start_date": "authoritative_exchange_listing_effective_date",
                    "listing_end_date": "authoritative_exchange_termination_effective_date" if end else None,
                },
                "start_evidence": start_evidence,
                "end_evidence": end_evidence,
                "evidence_digest": hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest(),
                "prohibited_inferences_used": [],
            }
        )
    open_episodes = [episode for episode in episodes if episode["listing_end_date"] is None]
    if len(open_episodes) > 1:
        raise SZSEFundLifecycleUnresolved(
            f"SZSE {code} has multiple unresolved open listing episodes"
        )
    if require_current_episode and len(open_episodes) != 1:
        raise SZSEFundLifecycleUnresolved(
            f"SZSE {code} current-population binding requires exactly one open listing episode"
        )
    return episodes


class SZSEFundLifecycleSource:
    """Repeatable official source adapter with retained byte-level provenance."""

    def __init__(
        self,
        root: Path,
        *,
        timeout: int = 60,
        session: requests.Session | None = None,
        receipts: MutableSequence[dict[str, Any]] | None = None,
    ) -> None:
        self.root = root
        self.timeout = timeout
        self.session = session or requests.Session()
        self.receipts = receipts if receipts is not None else []
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _milliseconds(day: str, *, end: bool = False) -> int:
        value = date.fromisoformat(day)
        moment = datetime.combine(value, datetime_time.max if end else datetime_time.min, SZSE_TIMEZONE)
        return int(moment.timestamp() * 1000)

    def _retain(
        self, prefix: str, identity: str, payload: bytes, *, suffix: str = ".json"
    ) -> tuple[str, str]:
        digest = sha256_bytes(payload)
        if suffix not in {".json", ".pdf"}:
            raise ValueError("unsupported retained source suffix")
        name = f"{_safe_segment(prefix)}_{_safe_segment(identity)}_{digest[:12]}{suffix}"
        try:
            retain_bytes_once(self.root, Path(name), payload, conflict_error=SZSEFundLifecycleSourceError)
        except SZSEFundLifecycleSourceError as exc:
            raise SZSEFundLifecycleSourceError(
                f"retained official response changed in place: {name}"
            ) from exc
        return name, digest

    def _record(
        self,
        *,
        route: str,
        url: str,
        started: float,
        response: requests.Response | None,
        retained: str | None = None,
        error: Exception | None = None,
    ) -> None:
        append_response_receipt(
            self.receipts,
            route=route,
            url=url,
            started=started,
            response=response,
            retained_response_file=retained,
            error=error,
        )

    def _curl_official(self, *, url: str, route: str, data: Mapping[str, Any] | None = None) -> bytes:
        """Bounded HTTP/1.1 fallback for official SZSE routes on Windows."""
        command = ["curl.exe", "--http1.1", "--silent", "--show-error", "--fail-with-body",
                   "--location", "--max-time", str(self.timeout),
                   "--header", "User-Agent: FinancialResearch/1.0",
                   "--header", f"Referer: {NOTICE_REFERER if data is not None else 'https://www.szse.cn/'}"]
        if data is not None:
            for key, value in data.items():
                command.extend(["--data-urlencode", f"{key}={value}"])
        command.append(url)
        last_error = ""
        for attempt in range(1, 4):
            started = time.monotonic()
            try:
                completed = subprocess.run(command, capture_output=True, check=False,
                                           timeout=self.timeout + 10)
                if completed.returncode == 0 and completed.stdout:
                    content = completed.stdout
                    self.receipts.append({"route": route, "url": url, "result": "success",
                                          "http_status": 200, "transport": "curl_http1_fallback",
                                          "attempts": attempt, "response_bytes": len(content),
                                          "response_sha256": hashlib.sha256(content).hexdigest(),
                                          "elapsed_seconds": round(time.monotonic() - started, 3), "error": None})
                    return content
                last_error = completed.stderr.decode("utf-8", errors="replace").strip() or f"curl exit {completed.returncode}"
            except (OSError, subprocess.TimeoutExpired) as exc:
                last_error = str(exc)
            self.receipts.append({"route": route, "url": url, "result": "failure",
                                  "transport": "curl_http1_fallback", "attempts": attempt,
                                  "elapsed_seconds": round(time.monotonic() - started, 3), "error": last_error})
            if attempt < 3:
                time.sleep(1.5 * attempt)
        raise SZSEFundLifecycleSourceError(f"{route} official HTTP/1.1 fallback failed: {last_error}")

    def _search_page(
        self,
        *,
        keyword: str,
        search_range: str,
        page: int,
        page_size: int,
        start: str | None,
        end: str | None,
        channel: str | None,
    ) -> Mapping[str, Any]:
        payload: dict[str, Any] = {
            "keyword": keyword,
            "time": self._milliseconds(start) if start else 0,
            "range": search_range,
            "currentPage": page,
            "pageSize": page_size,
            "scope": 1 if start else 0,
        }
        if channel:
            payload["channelCode[]"] = channel
        if end:
            payload["endTime"] = self._milliseconds(end, end=True)
        started = time.monotonic()
        response: requests.Response | None = None
        retained: str | None = None
        try:
            try:
                response = self.session.post(
                    SEARCH_URL,
                    data=payload,
                    headers={"User-Agent": "FinancialResearch/1.0", "Referer": NOTICE_REFERER},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                content = response.content
            except requests.exceptions.RequestException as exc:
                self._record(route="SZSE_fund_notice_search", url=SEARCH_URL, started=started,
                             response=response, error=exc)
                response = None
                content = self._curl_official(url=SEARCH_URL, route="SZSE_fund_notice_search", data=payload)
            retained, _digest = self._retain(
                "search", hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16], content
            )
            value = json.loads(content)
            if not isinstance(value, Mapping) or not isinstance(value.get("data"), list):
                raise SZSEFundLifecycleSourceError("SZSE Fund notice search returned an invalid envelope")
            total = value.get("totalSize")
            if not isinstance(total, int) or total < 0:
                raise SZSEFundLifecycleSourceError("SZSE Fund notice search lacks a valid totalSize")
            actual_page_size = value.get("pageSize")
            actual_page = value.get("currentPage")
            if (
                not isinstance(actual_page_size, int)
                or actual_page_size < 1
                or not isinstance(actual_page, int)
                or (actual_page != page and not (total == 0 and actual_page == 0))
            ):
                raise SZSEFundLifecycleSourceError("SZSE Fund notice search pagination metadata is invalid")
            if not all(isinstance(row, Mapping) and row.get("id") and row.get("docpubjsonurl") for row in value["data"]):
                raise SZSEFundLifecycleSourceError("SZSE Fund notice search contains an unbindable result")
            if response is not None:
                self._record(route="SZSE_fund_notice_search", url=SEARCH_URL, started=started, response=response, retained=retained)
            else:
                self.receipts[-1]["retained_response_file"] = retained
            return value
        except Exception as exc:
            self._record(route="SZSE_fund_notice_search", url=SEARCH_URL, started=started, response=response, retained=retained, error=exc)
            raise

    def search(
        self,
        *,
        keyword: str,
        search_range: str,
        start: str | None = None,
        end: str | None = None,
        page_size: int = 100,
        channel: str | None = CHANNEL,
        complete: bool = True,
    ) -> list[dict[str, Any]]:
        if search_range not in {"title", "content", "all"}:
            raise ValueError("unsupported SZSE notice search range")
        if bool(start) != bool(end):
            raise ValueError("bounded SZSE notice search requires both start and end")
        first = self._search_page(
            keyword=keyword, search_range=search_range, page=1, page_size=page_size,
            start=start, end=end, channel=channel,
        )
        total = int(first["totalSize"])
        actual_page_size = int(first["pageSize"])
        rows = [dict(row) for row in first["data"]]
        pages = (total + actual_page_size - 1) // actual_page_size if complete else 1
        for page in range(2, pages + 1):
            value = self._search_page(
                keyword=keyword, search_range=search_range, page=page,
                page_size=page_size, start=start, end=end, channel=channel,
            )
            if int(value["totalSize"]) != total:
                raise SZSEFundLifecycleSourceError("SZSE notice population changed during pagination")
            if int(value["pageSize"]) != actual_page_size:
                raise SZSEFundLifecycleSourceError("SZSE notice page size changed during pagination")
            rows.extend(dict(row) for row in value["data"])
        if complete and len(rows) != total:
            raise SZSEFundLifecycleSourceError("SZSE notice search did not deliver its declared population")
        return rows

    def fetch_document(self, result: Mapping[str, Any]) -> tuple[Mapping[str, Any], str, str]:
        path = str(result.get("docpubjsonurl") or "")
        if not path.startswith("/") or ".." in path:
            raise SZSEFundLifecycleSourceError("SZSE search result has an unsafe document path")
        url = NOTICE_ORIGIN + path
        started = time.monotonic()
        response: requests.Response | None = None
        retained: str | None = None
        try:
            try:
                response = self.session.get(
                    url,
                    headers={"User-Agent": "FinancialResearch/1.0", "Referer": NOTICE_REFERER},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                content = response.content
            except requests.exceptions.RequestException as exc:
                self._record(route="SZSE_fund_notice_document", url=url, started=started,
                             response=response, error=exc)
                response = None
                content = self._curl_official(url=url, route="SZSE_fund_notice_document")
            document_id = str(result.get("id") or "")
            retained, digest = self._retain("document", document_id, content)
            value = json.loads(content)
            if not isinstance(value, Mapping):
                raise SZSEFundLifecycleSourceError("SZSE Fund notice document is not a JSON object")
            data = value.get("data")
            if not isinstance(data, Mapping) or str(data.get("docId")) != document_id:
                raise SZSEFundLifecycleSourceError("SZSE search result and document identity disagree")
            if response is not None:
                self._record(route="SZSE_fund_notice_document", url=url, started=started, response=response, retained=retained)
            else:
                self.receipts[-1]["retained_response_file"] = retained
            return value, digest, retained
        except Exception as exc:
            self._record(route="SZSE_fund_notice_document", url=url, started=started, response=response, retained=retained, error=exc)
            raise

    def _fetch_pdf(self, result: Mapping[str, Any]) -> tuple[bytes, str, str, str]:
        source_url = str(result.get("docpuburl") or "")
        if source_url.startswith("http://"):
            source_url = "https://" + source_url.removeprefix("http://")
        if not source_url.startswith("https://disc.static.szse.cn/"):
            raise SZSEFundLifecycleSourceError("Fund disclosure is not hosted by the official SZSE disclosure surface")
        started = time.monotonic()
        response: requests.Response | None = None
        retained: str | None = None
        try:
            try:
                response = self.session.get(
                    source_url,
                    headers={"User-Agent": "FinancialResearch/1.0", "Referer": "https://www.szse.cn/"},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                content = response.content
            except requests.exceptions.RequestException as exc:
                self._record(route="SZSE_fund_disclosure_document", url=source_url, started=started,
                             response=response, error=exc)
                response = None
                content = self._curl_official(url=source_url, route="SZSE_fund_disclosure_document")
            if not content.startswith(b"%PDF"):
                raise SZSEFundLifecycleSourceError("SZSE Fund disclosure response is not a PDF")
            document_id = str(result.get("id") or hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:16])
            retained, digest = self._retain(
                "disclosure", document_id, content, suffix=".pdf"
            )
            if response is not None:
                self._record(route="SZSE_fund_disclosure_document", url=source_url, started=started,
                             response=response, retained=retained)
            else:
                self.receipts[-1]["retained_response_file"] = retained
            return content, digest, retained, source_url
        except Exception as exc:
            self._record(
                route="SZSE_fund_disclosure_document", url=source_url, started=started,
                response=response, retained=retained, error=exc,
            )
            raise

    def _disclosure_start_event(self, code: str, fund_kind: str) -> LifecycleEvent:
        results = self.search(
            keyword=code,
            search_range="content",
            page_size=100,
            channel=None,
            complete=False,
        )
        eligible_channels = {"lefuDisclosure_disc", "etfNotice_disc", "fundinfoNotice_disc"}
        title_markers = ("中期报告", "年度报告", "基金产品资料概要")
        extracted: list[LifecycleEvent] = []
        attempted = 0
        for result in results:
            title = _plain_text(str(result.get("doctitle") or ""))
            if result.get("chnlcode") not in eligible_channels or not any(marker in title for marker in title_markers):
                continue
            if fund_kind == "etf" and "ETF" not in title.upper() and "交易型开放式" not in title:
                continue
            if fund_kind == "lof" and "LOF" not in title.upper() and "上市开放式" not in title:
                continue
            if fund_kind == "public_reit" and "基础设施" not in title and "REIT" not in title.upper():
                continue
            payload, digest, retained, url = self._fetch_pdf(result)
            attempted += 1
            reader = PdfReader(io.BytesIO(payload))
            text = re.sub(
                r"\s+", "",
                "".join((page.extract_text() or "") for page in reader.pages[:15]),
            )
            if not any(
                re.search(pattern, text)
                for pattern in (
                    rf"基金主代码[：:]?{code}",
                    rf"基金代码[：:]?{code}",
                    rf"交易代码[：:]?{code}",
                )
            ):
                continue
            match = re.search(rf"(?:上市交易所及上市日期|上市日期)[：:]?(?:深圳证券交易所)?{_DATE}", text)
            if match is None:
                continue
            effective = _iso_date(match.group("year"), match.group("month"), match.group("day"))
            extracted.append(
                LifecycleEvent(
                    event_type="listing_start",
                    code=code,
                    effective_date=effective,
                    fund_kind=fund_kind,
                    fund_name=title,
                    document_id=str(result.get("id") or ""),
                    publication_date=_publication_date(result.get("docpubtime")),
                    document_url=url,
                    document_json_url="",
                    document_sha256=digest,
                    retained_response_file=retained,
                )
            )
            if len(extracted) >= 2:
                break
        if not extracted:
            raise SZSEFundLifecycleUnresolved(
                f"SZSE {code} has no authoritative listing-start notice or corroborating official Fund disclosure"
            )
        dates = {event.effective_date for event in extracted}
        if len(dates) != 1:
            raise SZSEFundLifecycleUnresolved(f"SZSE {code} official Fund disclosures conflict on listing date")
        if attempted > 1 and len(extracted) < 2:
            raise SZSEFundLifecycleUnresolved(
                f"SZSE {code} disclosure fallback could not independently repeat the listing date"
            )
        return extracted[0]

    def resolve_code(
        self,
        code: str,
        *,
        fund_kind: str | None = None,
        require_current_episode: bool = True,
    ) -> dict[str, Any]:
        code = str(code).zfill(6)
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError("SZSE Fund code must contain six digits")
        results = self.search(keyword=code, search_range="content")
        events: list[LifecycleEvent] = []
        for result in results:
            candidate = _plain_text(str(result.get("doctitle") or "") + str(result.get("doccontent") or ""))
            if "上市交易" not in candidate and "终止上市" not in candidate:
                continue
            document, digest, retained = self.fetch_document(result)
            events.extend(
                parse_official_notice(
                    document,
                    document_sha256=digest,
                    retained_response_file=retained,
                    requested_code=code,
                    requested_kind=fund_kind,
                )
            )
        if not any(event.event_type == "listing_start" for event in events):
            if fund_kind is None:
                raise SZSEFundLifecycleUnresolved(
                    f"SZSE {code} notice evidence lacks both listing start and a structured Fund classification hint"
                )
            events.append(self._disclosure_start_event(code, fund_kind))
        episodes = reconcile_code_lifecycle(code, events, require_current_episode=require_current_episode)
        material = {
            "code": code,
            "episodes": episodes,
            "search_result_count": len(results),
        }
        return {
            "schema_version": "fr_szse_fund_listing_lifecycle_resolution_v1",
            **material,
            "resolution_digest": hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest(),
            "source_receipts": [dict(row) for row in self.receipts],
        }

    def discover_event_documents(self, *, start: str, end: str) -> list[dict[str, Any]]:
        """Discover the bounded official lifecycle-document denominator.

        The returned search rows are discovery candidates, not promoted facts.
        A caller must fetch and parse each complete official document before
        reconciliation.  This split supports resumable historical bootstrap.
        """
        found: dict[str, dict[str, Any]] = {}
        for keyword in ("上市交易", "终止上市"):
            for row in self.search(
                keyword=keyword, search_range="title", start=start, end=end
            ):
                found[str(row["id"])] = dict(row)
        return [found[key] for key in sorted(found)]
