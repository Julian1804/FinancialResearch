# Data Connector Feasibility Audit

## Scope

This audit covers Phase 1 feasibility only. It does not start full crawlers and does not use paid, point-based, or recharge-based sources as the mainline.

## Official / Authoritative Source Rule

Trusted external facts must come from official institutions, exchanges, regulators, official authorized APIs, or open-source wrappers whose upstream source is traceable to official data. Media reposts, forums, public accounts, and second-hand commentary are not trusted external sources.

## Ready or Priority Sources

Recommended first connectors:

- `sec_edgar_companyfacts`
- `fred_public_csv`
- `treasury_fiscaldata`
- `world_bank_pink_sheet`
- `bls_public_api`
- `akshare_traceable_official` only for official-upstream datasets
- `cninfo_disclosure` for report discovery/download after rate/terms checks

Low-risk trusted eligible examples: sec_edgar_companyfacts, fred_public_csv, bls_public_api, treasury_fiscaldata, world_bank_pink_sheet, eia_open_data

## Deferred or Not Phase 1 Mainline

Deferred sources: eia_open_data, wind_terminal

- Wind is trusted eligible under license but not Phase 1 mainline.
- EIA is official, but key policy should be checked before implementation.
- Baostock and broad AKShare endpoints remain candidate until upstream provenance is recorded per dataset.

## Smoke Summary

- test count: 11
- success: 7
- failed: 2
- skipped: 2

Raw smoke results: `D:\workspace\FinancialResearch\runtime\data_connector_feasibility\connector_smoke_results.json`
Source registry: `D:\workspace\FinancialResearch\runtime\data_connector_feasibility\source_registry.json`

## Data Quality Gate

Authoritative source status is not enough. Every record must pass checks for numeric format, dates, nulls, duplicates, unit/currency, period, field mapping, continuity, range, source URL, retrieval timestamp, and checksum. A trusted source with failed quality checks becomes `trusted_source_but_quality_failed` or `needs_review`, not consumption-grade.

## Official References Used

- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- BLS Public Data API: https://www.bls.gov/developers/
- U.S. Treasury FiscalData API: https://fiscaldata.treasury.gov/api-documentation/
- World Bank Commodity Markets / Pink Sheet: https://www.worldbank.org/en/research/commodity-markets
- FRED public data portal: https://fred.stlouisfed.org/
- CNINFO disclosure portal: http://www.cninfo.com.cn/new/index
- Shanghai Stock Exchange disclosure portal: https://www.sse.com.cn/disclosure/listedinfo/announcement/
- Shenzhen Stock Exchange disclosure portal: https://www.szse.cn/disclosure/listed/notice/
