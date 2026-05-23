# Data Source Priority And Fallback Policy

Generated: 2026-05-23T10:05:16Z

FR keeps FRED, SEC, BaoStock, Tencent, Sina, THS, CNINFO and Eastmoney by data domain. It does not collapse onto AKShare or any other universal source.

Fallback sources are used when primary values are unavailable. Fallback values do not silently overwrite primary values and always retain source provenance.
