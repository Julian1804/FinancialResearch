# A+H Stock Module Framework

## Purpose

The A+H stock module connects company-level market data, structured financials, announcements, PDFs, news, forecasts, and backtests.

## A-share Daily Data

Current policy:

- Tencent via AKShare `stock_zh_a_hist_tx` is the primary daily candidate.
- BaoStock remains a validation/historical partner.
- Eastmoney daily history is deferred/fallback while unstable.
- OHLC can be field-level trusted candidate preview only where cross-source evidence supports it.
- Amount, turnover, pct_change, and preclose require limitations or derivation metadata.

## Structured Financials

Structured interfaces are the consumption-candidate mainline:

- Eastmoney balance sheet;
- Eastmoney profit sheet;
- Eastmoney cash flow;
- Eastmoney earnings table;
- Sina financial abstracts/indicators;
- THS financial abstract;
- CNINFO disclosure metadata.

Duplicate fields use primary/fallback/validation-reference rules.

## PDFs

PDFs are original report evidence for explanation and narrative. PDF parsing does not overwrite structured financial interface metrics. Parser failure does not block structured financial consumption.

## Forecast And Backtest

Forecasts must identify target metric, review date, testability, evidence, assumptions, and risk triggers. Backtests must preserve actual source and candidate/trust status.

