# Market Data Foundation Schema

Generated: 2026-05-20T08:17:00Z

The platform separates macro fundamentals, policy rates, market rates, FX, asset classes,
commodities and futures by economic meaning. Raw single-contract futures data must remain separate
from derived continuous contracts.

Pipeline: raw -> normalized -> QA -> catalog -> staging -> dashboard -> statistical report.

Futures schema includes exchange, contract_code, contract_month, expiry_date, OHLC, settlement,
volume, open_interest, contract_multiplier, continuous_contract_method and roll_adjustment_method.
