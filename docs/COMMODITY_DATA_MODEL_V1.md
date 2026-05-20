# Commodity Data Model v1

Generated: 2026-05-20T08:16:04Z

Commodity is part of the broader asset-class domain, but it has its own schema because
spot, benchmark, exchange settlement and futures contract data are not interchangeable.
Dashboard and report code must preserve those distinctions instead of presenting a
single “commodity price” as if it covered the whole market.

## Normalized Commodity Fields

- dataset_id
- source_id
- provider_name
- asset_class
- commodity_group
- commodity_category
- instrument_name
- underlying_commodity
- metric_name
- price_type: spot / futures / index / benchmark / settlement / average_price / unknown
- exchange: COMEX / NYMEX / LME / SHFE / INE / DCE / CZCE / World Bank / FRED / other / unknown
- contract_code
- contract_month
- frequency
- data_period_start
- data_period_end
- observation_date
- publish_date
- publish_date_source
- price
- value
- unit
- currency
- vintage_date
- revision_status
- retrieval_snapshot_id
- retrieved_at
- raw_path
- checksum
- quality_status
- trust_status
- candidate_only

## Futures Fields

Futures records add:

- contract_code
- underlying_asset
- futures_category
- contract_month
- expiry_date
- trade_date
- open
- high
- low
- close
- settlement
- volume
- open_interest
- contract_multiplier
- continuous_contract_method
- front_month_flag
- roll_adjustment_method

Raw single-contract futures are the source records. Continuous contracts are derived
datasets and must not overwrite raw exchange contracts.

## Current Coverage

World Bank Pink Sheet data is currently connected as benchmark / average-price style
evidence. It is not exchange futures data and must not be shown as COMEX, LME, SHFE,
DCE, CZCE, NYMEX or INE prices.

Current upgraded series:

- World Bank benchmark/average-price series: 10
- Exchange futures series: 0 connected
- Futures framework: schema ready, connector work deferred

All commodity outputs remain candidate/staging evidence and do not enter formal trusted
consumption.
