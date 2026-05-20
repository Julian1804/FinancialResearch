# Fund / ETF Manual Import Guide

Use these templates for official or authoritative fund lists, issuer product lists, exchange ETF lists, and holdings files.

Manual imports must include source identity, official/third-party classification, publish/disclosure date, and source URL where available. Manual imports are not automatically trusted; they enter candidate/staging with quality checks and can be used for Morningstar cross-source coverage validation.

CLI:

```powershell
D:\workspace\envs\financial_research_backend\Scripts\python.exe scripts\run_fund_etf_manual_import.py validate --input <csv-path> --template china_public_fund_official_list_template.csv
```
