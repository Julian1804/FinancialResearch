# Commodity Source Feasibility Audit

Generated: 2026-05-20T07:36:53Z

| Source | Status | Note |
| --- | --- | --- |
| World Bank Pink Sheet | connected | benchmark/monthly commodity prices; not exchange futures |
| FRED commodity series | connected_partial | WTI and other public series available; provider-specific definitions required |
| CME/COMEX/NYMEX | future_connector | Official historical settlements typically require CME DataMine/licensing or limited product pages; do not scrape aggressively. |
| LME | future_connector | Historical data generally requires licensing/subscription; current phase does not use it. |
| SHFE | small_sample_candidate | Official site may publish daily/monthly market data; requires endpoint-specific smoke before use. |
| INE | small_sample_candidate | Official energy exchange data may be available; endpoint stability must be verified. |
| DCE | small_sample_candidate | Official historical quotes may be available; endpoint/format needs separate connector. |
| CZCE | small_sample_candidate | Official data may be available; needs low-frequency endpoint verification. |
| Nasdaq Data Link | optional_candidate | Useful datasets may be free or paid; dataset-level license required. |
| Stooq/Yahoo/Investing | optional_candidate | Non-official or terms-sensitive; never trusted by default. |

No exchange prices are fabricated. Exchange connectors remain deferred unless a free official endpoint is verified.
