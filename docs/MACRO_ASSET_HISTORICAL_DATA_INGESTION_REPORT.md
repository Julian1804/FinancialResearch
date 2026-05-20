# Macro Asset Historical Data Ingestion Report

Generated: 2026-05-20T06:48:52Z

Scope: macro and asset/commodity historical data only. No A-share full history, no full financial report download, no OpenAI API, no parse_lab change, and no formal trusted consumption update.

Summary:

- retrieval_snapshot_id: `macro_asset_snapshot_20260520T064753Z`
- sources: {"fred_public_api": 74384, "treasury_fiscaldata": 4917, "world_bank_pink_sheet": 7576}
- series: 41
- records: 86877
- raw artifacts: 42
- quality: {"quality_passed": 40, "quality_warning": 1}
- metadata DB: `D:\workspace\FinancialResearch\runtime\macro_asset_historical_ingestion\macro_asset_metadata.sqlite`

| Source | Series | Category | Records | First | Latest | Quality |
|---|---|---|---:|---|---|---|
| fred_public_api | CPIAUCSL | inflation | 951 | 1947-01-01 | 2026-04-01 | quality_passed |
| fred_public_api | DCOILWTICO | energy | 10158 | 1986-01-02 | 2026-05-11 | quality_passed |
| fred_public_api | DFF | central_bank_policy | 26255 | 1954-07-01 | 2026-05-18 | quality_passed |
| fred_public_api | DGS10 | rates | 16079 | 1962-01-02 | 2026-05-18 | quality_passed |
| fred_public_api | DGS2 | rates | 12487 | 1976-06-01 | 2026-05-18 | quality_passed |
| fred_public_api | DTWEXBGS | currency | 5107 | 2006-01-02 | 2026-05-15 | quality_passed |
| fred_public_api | PAYEMS | employment | 1048 | 1939-01-01 | 2026-04-01 | quality_passed |
| fred_public_api | PPIACO | inflation | 1360 | 1913-01-01 | 2026-04-01 | quality_passed |
| fred_public_api | UNRATE | employment | 939 | 1948-01-01 | 2026-04-01 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:domestic_series | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:federal_financing_bank | treasury | 282 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:foreign_series | treasury | 303 | 2001-01-31 | 2026-03-31 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:government_account_series | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:government_account_series_inflation_securities | treasury | 187 | 2010-10-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:hope_bonds | treasury | 103 | 2008-08-31 | 2017-03-31 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:r.e.a._series | treasury | 132 | 2001-01-31 | 2011-12-31 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:special_purpose_vehicle | treasury | 72 | 2020-05-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:state_and_local_government_series | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:total_interest-bearing_debt | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:total_marketable | treasury | 302 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:total_non-marketable | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:totalmarketable | treasury | 1 | 2005-07-31 | 2005-07-31 | quality_warning |
| treasury_fiscaldata | avg_interest_rates:treasury_bills | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:treasury_bonds | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:treasury_floating_rate_notes_(frn) | treasury | 148 | 2014-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:treasury_inflation-indexed_bonds | treasury | 45 | 2001-01-31 | 2004-09-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:treasury_inflation-indexed_notes | treasury | 45 | 2001-01-31 | 2004-09-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:treasury_inflation-protected_securities_(tips) | treasury | 259 | 2004-10-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:treasury_notes | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:united_states_savings_inflation_securities | treasury | 302 | 2001-03-31 | 2026-04-30 | quality_passed |
| treasury_fiscaldata | avg_interest_rates:united_states_savings_securities | treasury | 304 | 2001-01-31 | 2026-04-30 | quality_passed |
| world_bank_pink_sheet | ALUMINUM | metals | 796 | 1960-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | COAL_AUS | energy | 676 | 1970-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | COPPER | metals | 796 | 1960-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | CRUDE_BRENT | energy | 796 | 1960-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | CRUDE_WTI | energy | 532 | 1982-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | GOLD | precious_metals | 796 | 1960-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | IRON_ORE | metals | 796 | 1960-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | SILVER | precious_metals | 796 | 1960-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | SOYBEANS | agriculture | 796 | 1960-01-01 | 2026-04-01 | quality_passed |
| world_bank_pink_sheet | WHEAT_US_HRW | agriculture | 796 | 1960-01-01 | 2026-04-01 | quality_passed |
