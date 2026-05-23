# Macro Module Framework

## Purpose

The macro module provides country, policy, inflation, employment, liquidity, reserves, and fiscal context for research. It is a foundation for capital-flow analysis, valuation context, and forecast revision.

## Data Categories

- CPI and inflation.
- PPI.
- Employment and unemployment.
- Payrolls.
- GDP.
- PMI.
- M0/M1/M2 and credit aggregates.
- Social financing.
- FX reserves and gold reserves.
- Policy rates.
- Central-bank balance sheets.
- Trade balance and current account.
- Fiscal balance and government debt.

## Time Semantics

Macro data must separate:

- `observation_date`;
- `data_period`;
- `release_date`;
- `publish_date`;
- `retrieved_at`;
- `vintage_date` or realtime fields when available.

If only observation date exists, the module must not invent publish date. It should mark release calendar limitation and avoid as-of-safe conclusions unless policy allows.

## Capital-Flow Relation

Macro data explains funding cost, currency pressure, inflation regime, employment cycle, policy stance, and liquidity. It is context, not direct flow by itself.

## QA Rules

- Numeric value checks.
- Unit and frequency checks.
- Duplicate series/date checks.
- Revision/vintage status.
- Publish date source classification.
- Extreme outlier flags retained rather than deleted.

