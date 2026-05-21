# AKShare Interface-Level Trust Classification

Generated: 2026-05-21T07:55:35Z

AKShare is a wrapper, not a single data source. Trust is classified per interface:

- `akshare_tencent_daily`: institutional_proxy_high_confidence_candidate (Tencent market data endpoint)
- `baostock_daily`: production_candidate_and_cross_validation_partner (Baostock A-share historical data service)
- `akshare_eastmoney_stock_zh_a_hist`: deferred (Eastmoney push2his)
- `akshare_unknown_or_unclassified`: candidate_only (unknown)
