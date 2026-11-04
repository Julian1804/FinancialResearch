from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


CSRC_INDEX_URL = (
    "https://www.csrc.gov.cn/csrc/c101900/c1029655/1029655/files/"
    "%E5%85%AC%E5%8B%9F%E5%9F%BA%E9%87%91%E4%BA%A7%E5%93%81%E7%B4%A2%E5%BC%95"
    "%EF%BC%88%E6%88%AA%E8%87%B320260630%EF%BC%89.xlsx"
)
EID_BASE = "http://eid.csrc.gov.cn/fund/disclose"
MANAGER_TYPES = ("4040-1010", "4040-1030", "4040-1070", "4040-1050")
SZSE_CATALOGS = {
    "etf": "1945",
    "lof": "1945_LOF",
    "public_reit": "scsj_cpml_jj_jcssjjlb",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=180) as response:
        payload = response.read()
    path.write_bytes(payload)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8", newline="\n")


def write_ndjson(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(node.text or "" for node in item.findall(".//x:t", namespace)) for item in root]


def parse_csrc_product_index(path: Path) -> list[dict[str, Any]]:
    """Read the compact CSRC product index without an Excel runtime."""
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as archive:
        strings = _xlsx_shared_strings(archive)
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    rows: list[list[str]] = []
    for row in root.findall(".//x:sheetData/x:row", namespace):
        cells: dict[int, str] = {}
        for cell in row.findall("x:c", namespace):
            reference = cell.attrib["r"]
            letters = re.match(r"[A-Z]+", reference).group(0)
            column = 0
            for letter in letters:
                column = column * 26 + ord(letter) - 64
            value_node = cell.find("x:v", namespace)
            value = "" if value_node is None else value_node.text or ""
            if cell.attrib.get("t") == "s" and value:
                value = strings[int(value)]
            cells[column] = value
        rows.append([cells.get(index, "") for index in range(1, 5)])
    expected = ["序号", "基金代码", "基金简称", "设立日期"]
    if rows[1] != expected:
        raise ValueError(f"unexpected CSRC product-index header: {rows[1]}")
    result = []
    for sequence, code, name, raw_date in rows[2:]:
        if not code:
            continue
        code = code.split(".")[0].zfill(6)
        if re.fullmatch(r"\d+(?:\.\d+)?", raw_date or ""):
            date = (datetime(1899, 12, 30) + timedelta(days=float(raw_date))).date().isoformat()
        else:
            date = raw_date[:10]
        result.append({
            "csrc_sequence": int(float(sequence)),
            "csrc_primary_code": code,
            "csrc_short_name": name,
            "fund_contract_effective_date": date,
        })
    return result


def fetch_manager_rosters(source_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for manager_type in MANAGER_TYPES:
        path = source_root / f"csrc_eid_manager_roster_{manager_type.replace('-', '_')}.json"
        if not path.exists():
            url = f"{EID_BASE}/fund_compay_affiche.do?type={manager_type}&fund_manager_select="
            download(url, path)
        for item in read_json(path)["aaData"]:
            rows.append({**item, "manager_type": manager_type})
    return rows


def fetch_manager_details(source_root: Path, rosters: Iterable[dict[str, Any]]) -> Path:
    output = source_root / "csrc_eid_manager_details.ndjson"
    if output.exists():
        return output
    rows = []
    for manager in sorted(rosters, key=lambda row: (row["manager_type"], row["code"])):
        params = urllib.parse.urlencode({"code": manager["code"], "type": manager["manager_type"]})
        url = f"{EID_BASE}/fund_compay_detail.do?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = response.read()
        data = json.loads(payload.decode("utf-8-sig"))
        rows.append({
            "source_url": url,
            "response_sha256": hashlib.sha256(payload).hexdigest(),
            "manager_type": manager["manager_type"],
            "manager_code": manager["code"],
            "response": data,
        })
    write_ndjson(output, rows)
    return output


def fetch_custodians(source_root: Path) -> Path:
    path = source_root / "csrc_eid_custodian_roster.json"
    if path.exists():
        return path
    ao_data = canonical_json([
        {"name": "sEcho", "value": 1},
        {"name": "iDisplayStart", "value": 0},
        {"name": "iDisplayLength", "value": 1000},
    ])
    body = urllib.parse.urlencode({"aoData": ao_data, "type": 2, "key": 2, "toOrder": 1}).encode()
    download(f"{EID_BASE}/org_show.do", path, data=body, headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded",
    })
    return path


def fetch_sse_funds(source_root: Path) -> Path:
    path = source_root / "sse_current_fund_list.json"
    if path.exists():
        return path
    params = {
        "isPagination": "true", "sqlId": "COMMON_JJZWZ_JJLB_L",
        "pageHelp.pageSize": "2000", "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1", "pageHelp.endPage": "1",
        "CATEGORY": "F000", "type": "inParams", "CATEGORY_ASC": "1",
    }
    url = "https://query.sse.com.cn/commonQuery.do?" + urllib.parse.urlencode(params)
    download(url, path, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://etf.sse.com.cn/fundlist/"})
    return path


def fetch_szse_funds(source_root: Path) -> Path:
    output = source_root / "szse_current_fund_lists.ndjson"
    if output.exists():
        return output
    rows = []
    for kind, catalog in SZSE_CATALOGS.items():
        first_url = (
            "https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&"
            + urllib.parse.urlencode({"CATALOGID": catalog, "TABKEY": "tab1", "PAGENO": 1})
        )
        request = urllib.request.Request(first_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.szse.cn/"})
        with urllib.request.urlopen(request, timeout=120) as response:
            first_payload = response.read()
        first = json.loads(first_payload.decode("utf-8-sig"))
        metadata = first[0]["metadata"]
        page_count = int(metadata["pagecount"])
        for page in range(1, page_count + 1):
            if page == 1:
                payload, data = first_payload, first
            else:
                url = (
                    "https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&"
                    + urllib.parse.urlencode({"CATALOGID": catalog, "TABKEY": "tab1", "PAGENO": page})
                )
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.szse.cn/"})
                with urllib.request.urlopen(request, timeout=120) as response:
                    payload = response.read()
                data = json.loads(payload.decode("utf-8-sig"))
            rows.append({
                "kind": kind, "catalog_id": catalog, "page": page,
                "response_sha256": hashlib.sha256(payload).hexdigest(), "response": data,
            })
    write_ndjson(output, rows)
    return output


def normalize_fund_type(code: str | None) -> str | None:
    return {
        "6020-6010": "equity_fund", "6020-6020": "money_market_fund",
        "6020-6030": "bond_fund", "6020-6040": "mixed_fund",
        "6020-6050": "qdii_fund", "6020-6060": "short_term_finance_bond_fund",
        "6020-6084": "fund_of_funds", "6020-6094": "fund_of_funds",
        "6020-6104": "commodity_fund",
    }.get(code)


def normalize_operation_type(code: str | None) -> str | None:
    return {"6030-1010": "closed_end", "6030-1020": "open_end", "6030-1030": "other"}.get(code)


def _daily_code_rows(path: Path) -> tuple[dict[str, set[str]], dict[tuple[str, str], dict[str, Any]]]:
    by_code: dict[str, set[str]] = defaultdict(set)
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for row in read_json(path)["aaData"]:
        fund = row.get("fund") or {}
        fund_id = str(fund.get("idStr") or "")
        code = str(row.get("code") or "").zfill(6)
        if not fund_id or not code:
            continue
        by_code[code].add(fund_id)
        key = (fund_id, code)
        item = pairs.setdefault(key, {
            "csrc_eid_fund_id": fund_id,
            "share_class_code": code,
            "share_class_names": set(),
            "value_classification_codes": set(),
            "valuation_date": row.get("valuationDate"),
            "has_reported_value": False,
        })
        if row.get("shortName"):
            item["share_class_names"].add(str(row["shortName"]))
        classification = (row.get("classification") or {}).get("code")
        if classification:
            item["value_classification_codes"].add(str(classification))
        item["has_reported_value"] = item["has_reported_value"] or any(
            row.get(field)
            for field in ("shareNetValue", "gainPer", "yearSevenDayYieldRate")
        )
    return by_code, pairs


def _validated_missing_code_map(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in read_ndjson(path):
        response = row["response"]
        if not response.get("isSuccess") or not response.get("fundId"):
            raise ValueError(f"CSRC EID validation failed for {row['csrc_primary_code']}")
        result[row["csrc_primary_code"]] = str(response["fundId"])
    return result


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", value))).strip()


def parse_fund_detail_html(path: Path, *, csrc_eid_fund_id: str) -> dict[str, Any]:
    """Extract the regulator-rendered basic product panel for review samples."""
    source = path.read_text(encoding="utf-8")
    cells = [_text(value) for value in re.findall(r"<td\b[^>]*>(.*?)</td>", source, re.S | re.I)]
    labels = {
        "基金名称": "fund_name",
        "基金代码": "primary_code",
        "基金运作方式": "operation_type",
        "基金类别": "fund_type",
        "基金管理人": "manager_name",
        "基金托管人": "custodian_name",
        "基金合同生效日期": "contract_effective_date",
        "基金合同存续期截止日": "contract_end_date",
    }
    result: dict[str, Any] = {"csrc_eid_fund_id": str(csrc_eid_fund_id)}
    for element_id, target in (("sp_fundName", "fund_name"), ("sp_fundCode", "primary_code")):
        match = re.search(
            rf'id=["\']{element_id}["\'][^>]*>(.*?)</td>', source, re.S | re.I
        )
        if match:
            result[target] = _text(match.group(1)) or None
    for index, cell in enumerate(cells[:-1]):
        target = labels.get(cell)
        if target and target not in result:
            result[target] = cells[index + 1] or None
    missing = sorted(set(labels.values()) - set(result))
    if missing:
        raise ValueError(f"fund detail page lacks basic fields {missing}: {path}")
    result.update({
        "source_file": path.name,
        "source_url": f"{EID_BASE}/fund_detail.do?fundId={csrc_eid_fund_id}",
        "source_sha256": sha256_file(path),
    })
    return result


def _szse_code(row: dict[str, Any]) -> str:
    value = str(row.get("sys_key") or "")
    match = re.search(r"(?:code=|>)(\d{6})(?:<|$)", value)
    if not match:
        raise ValueError(f"SZSE row has no six-digit security code: {value}")
    return match.group(1)


def _szse_name(row: dict[str, Any]) -> str | None:
    value = html.unescape(str(row.get("kzjcurl") or ""))
    match = re.search(r"[?&]name=([^'&]+)", value)
    return urllib.parse.unquote(match.group(1)).strip() if match else None


def build_authoritative_owner(source_root: Path) -> dict[str, list[dict[str, Any]]]:
    index_rows = parse_csrc_product_index(source_root / "csrc_public_fund_product_index_20260630.xlsx")
    detail_rows = read_ndjson(source_root / "csrc_eid_manager_details.ndjson")
    custodians = read_json(source_root / "csrc_eid_custodian_roster.json")["aaData"]
    sse_rows = read_json(source_root / "sse_current_fund_list.json")["result"]
    szse_pages = read_ndjson(source_root / "szse_current_fund_lists.ndjson")

    as_of_code_map, as_of_pairs = _daily_code_rows(
        source_root / "csrc_eid_daily_all_20260630.json"
    )
    current_code_map, current_pairs = _daily_code_rows(
        source_root / "csrc_eid_daily_all_20260907.json"
    )
    validated_map = _validated_missing_code_map(
        source_root / "csrc_eid_validate_fund_missing_index_codes.ndjson"
    )

    detail_products: dict[str, dict[str, Any]] = {}
    managers: dict[str, dict[str, Any]] = {}
    for item in detail_rows:
        response = item["response"]
        company = response["fundCompany"]
        code = str(item["manager_code"])
        managers[code] = {
            "authority": "CSRC_EID", "manager_code": code,
            "manager_name": company.get("cname"), "manager_short_name": company.get("shortName"),
            "manager_type_code": item["manager_type"], "established_date": company.get("foundDate"),
            "source_url": item["source_url"], "source_response_sha256": item["response_sha256"],
        }
        for fund in response.get("fundlist", []):
            fid = str(fund["fundId"])
            candidate = {
                "csrc_eid_fund_id": fid,
                "csrc_primary_code": str(fund.get("fundCode") or "").zfill(6),
                "fund_name": fund.get("fundName"), "fund_type_code": fund.get("fundType"),
                "fund_status_code": fund.get("fundStatus"), "manager_code": code,
                "manager_name": company.get("cname"), "source_url": item["source_url"],
                "source_response_sha256": item["response_sha256"],
            }
            if fid in detail_products and detail_products[fid] != candidate:
                raise ValueError(f"conflicting CSRC EID product record: {fid}")
            detail_products[fid] = candidate

    products = []
    for index in index_rows:
        code = index["csrc_primary_code"]
        candidates = as_of_code_map.get(code, set())
        route = "same_date_csrc_eid_share_class_observation"
        if len(candidates) == 1:
            fid = next(iter(candidates))
        elif not candidates and code in validated_map:
            fid = validated_map[code]
            route = "csrc_eid_direct_code_validation"
        else:
            raise ValueError(f"CSRC index row has unresolved or ambiguous EID identity: {code}")
        detail = detail_products.get(fid, {})
        products.append({
            **index,
            "csrc_eid_fund_id": fid,
            "fund_name": detail.get("fund_name") or index["csrc_short_name"],
            "fund_type_code": detail.get("fund_type_code"),
            "fund_status_code": detail.get("fund_status_code"),
            "manager_code": detail.get("manager_code"),
            "manager_name": detail.get("manager_name"),
            "manager_source_url": detail.get("source_url"),
            "product_identity_basis": (
                "one unique CSRC product-index row plus one unique CSRC EID product binding"
            ),
            "eid_binding_route": route,
            "as_of_date": "2026-06-30",
            "population_basis": "csrc_product_index_2026_06_30",
            "lifecycle_status_at_as_of": "present_in_csrc_public_fund_product_index",
            "source_refs": [
                "source/csrc_public_fund_product_index_20260630.xlsx",
                (
                    "source/csrc_eid_daily_all_20260630.json"
                    if route == "same_date_csrc_eid_share_class_observation"
                    else "source/csrc_eid_validate_fund_missing_index_codes.ndjson"
                ),
            ],
        })
    indexed_fids = {row["csrc_eid_fund_id"] for row in products}
    if len(indexed_fids) != len(products):
        raise ValueError("CSRC product index unexpectedly maps multiple rows to one EID product")

    post_detail_rows = []
    for path in sorted((source_root / "post_index_fund_details").glob("fund_*.html")):
        fund_id = path.stem.rsplit("_", 1)[1]
        if fund_id in indexed_fids:
            continue
        post_detail_rows.append(parse_fund_detail_html(path, csrc_eid_fund_id=fund_id))
    current_fids = {fund_id for fund_ids in current_code_map.values() for fund_id in fund_ids}
    exchange_validated = {
        str(row["response"]["fundId"]): row["exchange_code"]
        for row in read_ndjson(source_root / "csrc_eid_validate_fund_unlinked_exchange_codes.ndjson")
        if row["response"].get("isSuccess") and row["response"].get("fundId")
    }
    for detail in post_detail_rows:
        fund_id = detail["csrc_eid_fund_id"]
        if fund_id not in current_fids and fund_id not in exchange_validated:
            raise ValueError(f"post-index fund detail lacks a current discovery route: {fund_id}")
        products.append({
            "csrc_sequence": None,
            "csrc_primary_code": detail["primary_code"],
            "csrc_short_name": detail["fund_name"],
            "fund_contract_effective_date": detail["contract_effective_date"],
            "csrc_eid_fund_id": fund_id,
            "fund_name": detail["fund_name"],
            "fund_type_code": None,
            "fund_type_label": detail["fund_type"],
            "fund_status_code": None,
            "operation_type_label": detail["operation_type"],
            "manager_code": None,
            "manager_name": detail["manager_name"],
            "custodian_name": detail["custodian_name"],
            "product_identity_basis": (
                "one CSRC EID product detail bound to a post-index current EID valuation or "
                "official exchange listing discovery"
            ),
            "eid_binding_route": (
                "post_index_current_eid_observation"
                if fund_id in current_fids
                else "post_index_exchange_listing_plus_csrc_eid_validation"
            ),
            "population_basis": "authoritative_post_index_discovery",
            "as_of_date": "2026-09-08",
            "lifecycle_status_at_as_of": "present_in_current_authoritative_source",
            "source_refs": [
                f"source/post_index_fund_details/{detail['source_file']}",
                (
                    "source/csrc_eid_daily_all_20260907.json"
                    if fund_id in current_fids
                    else "source/csrc_eid_validate_fund_unlinked_exchange_codes.ndjson"
                ),
            ],
        })

    all_fids = {row["csrc_eid_fund_id"] for row in products}
    if len(all_fids) != len(products):
        raise ValueError("authoritative product owner contains duplicate CSRC EID products")

    product_by_fid = {row["csrc_eid_fund_id"]: row for row in products}
    share_classes = []
    for (fid, code), row in sorted(as_of_pairs.items(), key=lambda item: (int(item[0][0]), item[0][1])):
        if fid not in indexed_fids:
            continue
        share_classes.append({
            "csrc_eid_fund_id": fid,
            "csrc_product_sequence": product_by_fid[fid]["csrc_sequence"],
            "share_class_code": code,
            "share_class_names": sorted(row["share_class_names"]),
            "value_classification_codes": sorted(row["value_classification_codes"]),
            "valuation_date": row["valuation_date"],
            "has_reported_value": row["has_reported_value"],
            "share_class_identity_basis": (
                "one CSRC EID fundId plus one CSRC-published fund code; repeated value templates "
                "do not create additional share classes"
            ),
            "source_refs": ["source/csrc_eid_daily_all_20260630.json"],
        })
    for (fid, code), row in sorted(
        current_pairs.items(), key=lambda item: (int(item[0][0]), item[0][1])
    ):
        if fid in indexed_fids or fid not in all_fids:
            continue
        share_classes.append({
            "csrc_eid_fund_id": fid,
            "csrc_product_sequence": None,
            "share_class_code": code,
            "share_class_names": sorted(row["share_class_names"]),
            "value_classification_codes": sorted(row["value_classification_codes"]),
            "valuation_date": row["valuation_date"],
            "has_reported_value": row["has_reported_value"],
            "share_class_identity_basis": (
                "one CSRC EID fundId plus one current CSRC-published fund code"
            ),
            "source_refs": ["source/csrc_eid_daily_all_20260907.json"],
        })
    existing_pairs = {(row["csrc_eid_fund_id"], row["share_class_code"]) for row in share_classes}
    for product in products:
        pair = (product["csrc_eid_fund_id"], product["csrc_primary_code"])
        if pair in existing_pairs:
            continue
        share_classes.append({
            "csrc_eid_fund_id": product["csrc_eid_fund_id"],
            "csrc_product_sequence": product["csrc_sequence"],
            "share_class_code": product["csrc_primary_code"],
            "share_class_names": [product["csrc_short_name"]],
            "value_classification_codes": [],
            "valuation_date": None,
            "has_reported_value": False,
            "share_class_identity_basis": (
                "the authoritative product primary code uniquely resolves back to the same "
                "CSRC EID product and is retained as its primary fund-code line"
            ),
            "source_refs": product["source_refs"],
        })
    share_classes.sort(key=lambda row: (
        row["csrc_product_sequence"] is None,
        row["csrc_product_sequence"] or 0,
        int(row["csrc_eid_fund_id"]),
        row["share_class_code"],
    ))

    product_fid_by_code: dict[str, str] = {}
    for product in products:
        product_fid_by_code[product["csrc_primary_code"]] = product["csrc_eid_fund_id"]
    for mapping in (as_of_code_map, current_code_map):
        for code, fids in mapping.items():
            known = sorted(fid for fid in fids if fid in all_fids)
            if len(known) == 1:
                product_fid_by_code[code] = known[0]

    listings = []
    for row in sse_rows:
        code = str(row["FUND_CODE"]).zfill(6)
        fid = product_fid_by_code.get(code)
        listings.append({
            "venue": "SSE", "exchange_code": code, "listing_name": row["FUND_EXPANSION_ABBR"],
            "listing_date": row["LISTING_DATE"] or None, "manager_name": row["COMPANY_NAME"],
            "product_structure_code": row["CATEGORY"], "index_name": row.get("INDEX_NAME"),
            "csrc_eid_fund_id": fid,
            "csrc_product_sequence": product_by_fid[fid]["csrc_sequence"] if fid else None,
            "product_binding_status": "proved" if fid else "post_denominator_or_unresolved",
            "observation_date": "2026-09-08",
            "source_refs": ["source/sse_current_fund_list.json"],
        })
    for page in szse_pages:
        response = page["response"]
        for table in response:
            for row in table.get("data", []):
                code = _szse_code(row)
                fid = product_fid_by_code.get(code)
                listings.append({
                    "venue": "SZSE", "catalog_kind": page["kind"],
                    "exchange_code": code, "listing_name": _szse_name(row),
                    "listing_date": None, "manager_name": row.get("glrmc"),
                    "csrc_eid_fund_id": fid,
                    "csrc_product_sequence": product_by_fid[fid]["csrc_sequence"] if fid else None,
                    "product_binding_status": "proved" if fid else "post_denominator_or_unresolved",
                    "observation_date": "2026-09-08",
                    "source_refs": ["source/szse_current_fund_lists.ndjson"],
                })

    manager_relationships = []
    for product in products:
        if product.get("manager_code"):
            manager_relationships.append({
                "csrc_eid_fund_id": product["csrc_eid_fund_id"],
                "manager_code": product["manager_code"],
                "relationship_type": "managed_by",
                "relationship_basis": "CSRC EID manager detail fundlist",
                "source_refs": [product["manager_source_url"]],
            })

    sample_details = []
    for path in sorted(source_root.glob("sample_fund_*.html")):
        fund_id = path.stem.rsplit("_", 1)[1]
        sample_details.append(parse_fund_detail_html(path, csrc_eid_fund_id=fund_id))

    manager_code_by_name = {
        row["manager_name"]: row["manager_code"]
        for row in managers.values()
        if row.get("manager_name")
    }
    organization_relationships: dict[tuple[str, str, str], dict[str, Any]] = {}
    for relationship in manager_relationships:
        key = (relationship["csrc_eid_fund_id"], "managed_by", relationship["manager_code"])
        organization_relationships[key] = relationship
    for listing in listings:
        fund_id = listing.get("csrc_eid_fund_id")
        manager_name = listing.get("manager_name")
        manager_code = manager_code_by_name.get(manager_name)
        if fund_id and manager_code:
            key = (fund_id, "managed_by", manager_code)
            organization_relationships.setdefault(key, {
                "csrc_eid_fund_id": fund_id,
                "manager_code": manager_code,
                "manager_name": manager_name,
                "relationship_type": "managed_by",
                "relationship_basis": "official exchange current-fund row matched to CSRC manager roster",
                "source_refs": listing["source_refs"],
            })
    for detail in sample_details + post_detail_rows:
        fund_id = detail["csrc_eid_fund_id"]
        if fund_id not in all_fids:
            continue
        manager_code = manager_code_by_name.get(detail.get("manager_name"))
        if manager_code:
            key = (fund_id, "managed_by", manager_code)
            organization_relationships.setdefault(key, {
                "csrc_eid_fund_id": fund_id,
                "manager_code": manager_code,
                "manager_name": detail["manager_name"],
                "relationship_type": "managed_by",
                "relationship_basis": "CSRC EID product basic-information panel",
                "source_refs": [f"source/{detail['source_file']}"],
            })
        if detail.get("custodian_name"):
            key = (fund_id, "custodied_by", detail["custodian_name"])
            organization_relationships[key] = {
                "csrc_eid_fund_id": fund_id,
                "custodian_name": detail["custodian_name"],
                "relationship_type": "custodied_by",
                "relationship_basis": "CSRC EID product basic-information panel",
                "source_refs": [
                    (
                        f"source/post_index_fund_details/{detail['source_file']}"
                        if detail in post_detail_rows
                        else f"source/{detail['source_file']}"
                    )
                ],
            }

    return {
        "products": sorted(products, key=lambda row: (
            row["population_basis"] != "csrc_product_index_2026_06_30",
            row["csrc_sequence"] or 0,
            int(row["csrc_eid_fund_id"]),
        )),
        "share_classes": share_classes,
        "managers": sorted(managers.values(), key=lambda row: row["manager_code"]),
        "custodians": sorted(custodians, key=lambda row: row["bankCode"]),
        "organization_relationships": sorted(
            organization_relationships.values(),
            key=lambda row: (
                int(row["csrc_eid_fund_id"]), row["relationship_type"],
                row.get("manager_code") or row.get("custodian_name") or "",
            ),
        ),
        "sample_product_details": sample_details,
        "post_index_product_details": post_detail_rows,
        "listings": sorted(listings, key=lambda row: (row["venue"], row["exchange_code"])),
        "detail_products": sorted(detail_products.values(), key=lambda row: int(row["csrc_eid_fund_id"])),
    }
