# Capital Flow Research Framework

## Research Layers

1. Macro and policy regime.
2. Rates, FX, and liquidity.
3. Asset-class performance and valuation pressure.
4. Fund, ETF, holdings, and exposure data.
5. Sector and country allocation.
6. Company-level impact.
7. Events, news, and policy shocks.
8. Forecast, backtest, and revision.

## Data Interpretation

Capital flow research is evidence-weighted. A single proxy is not sufficient. Multiple layers should be connected:

- macro release and policy stance;
- rates and FX movement;
- asset prices;
- ETF/fund trading activity;
- AUM, NAV, and holdings;
- country/sector/currency exposure;
- company-level fundamentals and announcements.

## Status Labels

- `actual_flow`: only when a source explicitly defines and provides actual or estimated flow.
- `flow_proxy`: observable trace such as volume, amount, NAV, AUM, shares outstanding, holdings, or exposure change.
- `price_context`: market price behavior that may be caused by many factors.
- `event_context`: policy, news, geopolitical, or company event evidence.
- `insufficient_evidence`: evidence is missing or not safe for the requested inference.

## AI Workflow

AI analysis should consume packeted evidence, not unbounded external facts. Reports must preserve candidate/trusted labels and insufficient-evidence notes.

