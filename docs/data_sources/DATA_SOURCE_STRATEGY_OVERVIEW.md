# Data Source Strategy Overview

## Principle

Data sources are judged by data domain and interface, not by platform name alone.

FR can use official sources, licensed institutional sources, institutional proxy sources, open-source wrappers, and candidate third-party sources in parallel if provenance, field quality, QA, and storage boundaries are clear.

## Source Classes

- `official_source`: SEC, FRED, U.S. Treasury, CNINFO where official disclosure metadata applies.
- `licensed_institutional_source`: Morningstar Direct / Analytics Lab.
- `institutional_proxy_source`: stable wrapper/interface to mature market-data platforms such as Tencent, Eastmoney, THS, Sina, or similar.
- `open_source_api_wrapper_candidate`: AKShare, BaoStock, and similar wrappers when upstream provenance and stability are known.
- `media_or_news_source`: news, event, sentiment, and clue sources; not trusted for key facts without extra checks.
- `manual_validation_only`: manual import or human verification support, not a long-term primary pipeline.

## Current Retained Sources

- FRED: macro, rates, inflation, employment, USD liquidity.
- SEC: filings, company facts, regulatory disclosure.
- BaoStock: A-share daily validation/historical partner where stable.
- Tencent via AKShare: current primary A-share daily candidate.
- CNINFO: official China disclosure metadata and PDFs.
- Eastmoney: interface-level use for structured statements, earnings, notices, news; daily history deferred.
- Sina and THS: financial abstract and indicator interfaces under continued testing.
- Morningstar: licensed institutional source for funds, ETFs, holdings, exposure, returns, and entity anchors.

## Do Not Do

- Do not treat AKShare as the only source.
- Do not exclude Eastmoney as a whole; evaluate each interface.
- Do not force unstable Eastmoney daily history into the default chain.
- Do not treat media/news sources as institutional databases.
- Do not let PDF parsing overwrite structured financial interfaces.

