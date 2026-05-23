# Flow Proxy And Exposure Methodology

## Proxy Hierarchy

Level 1: trading activity proxy

- volume;
- amount;
- turnover.

Level 2: price performance proxy

- NAV change;
- price momentum;
- returns.

Level 3: size proxy

- AUM;
- net assets.

Level 4: subscription proxy

- shares outstanding change.

Level 5: allocation proxy

- holdings change;
- sector exposure change;
- country exposure change;
- currency exposure change.

Level 6: actual or estimated flow

- only allowed when the data source explicitly provides net flow or estimated net flow and gives enough definition.

## Morningstar Rules

Morningstar is a licensed institutional source. It can be a high-confidence candidate for fields it is entitled to provide, but it is not a public free source and not automatically platform-wide trusted.

Current Morningstar caveats:

- TNA/ENF remains sidecar with `blocked_unit_scale_unknown`.
- Flow proxy remains `proxy_not_actual_flow`.
- Non-China equities are entity shells unless an approved future data product allows time series.

## A-share / ETF Rules

OHLC field-level trusted candidate preview is available for the controlled A-share/ETF product. Amount, turnover, pct_change, and preclose remain limited unless their upgrade evidence is closed.

