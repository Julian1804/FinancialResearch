# Forecast / Backtest / Revision Module Framework

## Purpose

This module turns analysis claims into testable forecast records, backtest results, and revision candidates.

## Forecast Contract

Forecast items should include:

- forecast type;
- target metric;
- expected direction or range;
- forecast horizon;
- review date;
- confidence;
- thesis;
- supporting evidence;
- assumptions;
- invalidation triggers;
- data dependency;
- testability status.

## Backtest Rules

- Use existing governed data only.
- If actual data is missing, mark `insufficient_actual_data`.
- If forecast is qualitative, mark manual review required.
- Do not overwrite original forecast records.
- Preserve actual source, quality, trust status, and candidate-only notes.

## Revision Workflow

Backtest misses or inconclusive results create revision candidates. The system should not automatically change an investment view; it should generate a user-review prompt and record why revision may be needed.

