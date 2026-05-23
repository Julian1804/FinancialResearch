# A-share Multi-source Policy

## Current Daily Market Strategy

Tencent `stock_zh_a_hist_tx` through AKShare is the current primary A-share daily candidate. It is not the only source.

BaoStock remains a stable supplement, validation partner, and historical data source where available.

Eastmoney daily history `stock_zh_a_hist` is currently unstable for primary use and is downgraded to fallback/deferred.

## Tencent Field Policy

Raw fields:

- date;
- open;
- close;
- high;
- low;
- amount.

Supplemented fields:

- `stock_code`: parsed from `sh/sz/bj` symbol;
- `exchange`: parsed from `sh/sz/bj` symbol;
- `adjust_type`: request adjustment mode;
- `source`: `akshare_tencent`;
- `upstream`: `tencent`.

Derivable fields:

- `price_change = close_t - close_t_minus_1`;
- `pct_change = close_t / close_t_minus_1 - 1`;
- `amplitude = (high - low) / close_t_minus_1`.

Derivation must record:

- `derivation_method`;
- `previous_close_source`;
- adjustment basis (`raw`, `qfq`, or `hfq`);
- null for first observation without previous close.

Do not hard-calculate as consumption-grade:

- turnover amount;
- turnover rate.

## Eastmoney Interface-Level Policy

Eastmoney daily history:

- `unstable_for_primary`;
- `fallback_or_deferred`;
- `monitor_required`.

Eastmoney structured interfaces retained:

- balance sheet yearly;
- profit sheet yearly;
- cash-flow sheet yearly;
- earnings table;
- notices;
- company news.

Future Eastmoney-specific connectors should be created only for fields unavailable elsewhere and only after stability metrics are recorded.

## Financial Interfaces

Sina and THS financial interfaces remain under continued testing. Duplicate fields use primary/fallback rules and preserve provenance.

