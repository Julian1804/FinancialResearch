"""Venue-aware China-region Equity identifier helpers.

Provider symbols remain aliases.  These helpers only normalize exchange listing
codes at API and source-contract boundaries; they do not decide economic
identity or listing continuity.
"""

from __future__ import annotations

from typing import Any


MAINLAND_VENUES = frozenset({"SSE", "SZSE", "BSE"})
HKEX_VENUES = frozenset({"HKEX", "XHKG"})


def canonical_equity_venue(value: Any) -> str:
    venue = str(value or "").strip().upper()
    if venue == "XHKG":
        return "HKEX"
    if venue not in MAINLAND_VENUES | {"HKEX"}:
        raise ValueError(f"unsupported China-region Equity venue: {value!r}")
    return venue


def normalize_listing_code(venue: Any, value: Any) -> str:
    canonical_venue = canonical_equity_venue(venue)
    if isinstance(value, (int, float)) and float(value).is_integer():
        value = str(int(value))
    text = str(value or "").strip().upper()
    for token in ("HKEX:", "XHKG:"):
        if text.startswith(token):
            text = text[len(token):]
    if text.endswith(".HK"):
        text = text[:-3]
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    width = 5 if canonical_venue == "HKEX" else 6
    code = text.zfill(width)
    if len(code) != width or not code.isdigit():
        raise ValueError(f"invalid {canonical_venue} listing code: {value!r}")
    return code


def provider_symbol(venue: Any, code: Any, *, provider: str) -> str:
    canonical_venue = canonical_equity_venue(venue)
    normalized = normalize_listing_code(canonical_venue, code)
    source = provider.strip().lower()
    if source == "tencent":
        prefixes = {"SSE": "sh", "SZSE": "sz", "BSE": "bj", "HKEX": "hk"}
        return f"{prefixes[canonical_venue]}{normalized}"
    if source in {"sina", "akshare_stock_hk_daily"} and canonical_venue == "HKEX":
        return normalized
    raise ValueError(f"unsupported provider symbol contract: {provider}/{canonical_venue}")
