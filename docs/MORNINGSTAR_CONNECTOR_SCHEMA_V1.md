# Morningstar Connector Schema v1

Morningstar data is licensed-source candidate evidence. These schemas prepare ingestion without promoting records into formal trusted consumption.

## Fund / ETF Master Schema

`dataset_id`, `source_id`, `morningstar_sec_id`, `isin`, `ticker`, `exchange`, `fund_name`, `fund_type`, `category`, `domicile`, `currency`, `inception_date`, `provider`, `retrieved_at`, `entitlement_status`, `quality_status`, `trust_status`, `candidate_only`

## Holdings Schema

`dataset_id`, `source_id`, `portfolio_id`, `holding_date`, `holding_name`, `holding_identifier`, `asset_type`, `weight`, `shares`, `market_value`, `sector`, `country`, `currency`, `retrieved_at`, `entitlement_status`, `quality_status`, `trust_status`, `candidate_only`

## Performance / NAV Schema

`dataset_id`, `source_id`, `morningstar_sec_id`, `observation_date`, `publish_date`, `value`, `value_type`, `currency`, `frequency`, `retrieved_at`, `entitlement_status`, `quality_status`, `trust_status`, `candidate_only`
