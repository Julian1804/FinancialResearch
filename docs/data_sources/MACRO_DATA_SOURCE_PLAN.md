# Macro Data Source Plan

## Scope

Macro data supports capital-flow research by providing economic, policy, inflation, employment, liquidity, currency, and reserve context.

## Current Priority Sources

- FRED for US macro, rates, inflation, employment, and USD conditions.
- U.S. Treasury FiscalData for Treasury and fiscal datasets.
- BLS when available; public API threshold and fallback status must be respected.
- Official national sources for China, Japan, Euro Area, and UK when stable automation is possible.

## Time Semantics

Macro data must distinguish:

- observation date;
- data period;
- release date;
- publish date;
- retrieval date;
- vintage/realtime fields when available.

If release date is unavailable, do not fabricate publish date. Mark `release_calendar_limited` or `publish_date_unavailable`.

## As-of Research Rule

As-of research can only use information available by the as-of date. Revised data must preserve vintage or revision notes where possible.

## Relation To Capital Flow

Macro data helps explain:

- rate differentials;
- USD liquidity;
- inflation regime;
- policy cycle;
- unemployment and payroll pressure;
- FX reserve and currency stress;
- fiscal and debt conditions.

