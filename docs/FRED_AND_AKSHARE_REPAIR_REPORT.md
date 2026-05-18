# FRED and AKShare Repair Report

## Secrets Safety

- local secrets exists: True
- FRED key present: True
- masked FRED key: `****f5aa`
- full key logged: False

## FRED Smoke

| Series | Status | Records | Quality | Trust | Error |
|---|---:|---:|---|---|---|
| DGS10 | success | 30 | quality_passed | trusted_by_real_external_candidate |  |
| DCOILWTICO | success | 29 | quality_passed | trusted_by_real_external_candidate |  |
| CPIAUCSL | success | 3 | quality_passed | trusted_by_real_external_candidate |  |

FRED remains candidate-only and is not connected to formal trusted consumption.

## AKShare Network

- akshare import ok: True
- akshare version: 1.18.62
- likely cause: vpn_or_proxy_or_upstream_disconnect
- user next action: Try disabling VPN, switching to another Hong Kong/mainland-friendly node, clearing HTTP_PROXY/HTTPS_PROXY/ALL_PROXY, or opening the Eastmoney endpoint in a browser.

| Test | Status | Records | Quality | Error |
|---|---:|---:|---|---|
| stock_zh_a_hist_000001 | failed | 0 | quality_failed | ProxyError: HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61%2Cf116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=0&secid=0.000001&beg=20260403&end=20260518 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response'))) |
| stock_zh_a_hist_600519 | failed | 0 | quality_failed | ProxyError: HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61%2Cf116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=0&secid=1.600519&beg=20260403&end=20260518 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response'))) |
| stock_zh_a_spot_em | failed | 0 | quality_failed | ProxyError: HTTPSConnectionPool(host='82.push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m%3A0+t%3A6%2Cm%3A0+t%3A80%2Cm%3A1+t%3A2%2Cm%3A1+t%3A23%2Cm%3A0+t%3A81+s%3A2048&fields=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6%2Cf7%2Cf8%2Cf9%2Cf10%2Cf12%2Cf13%2Cf14%2Cf15%2Cf16%2Cf17%2Cf18%2Cf20%2Cf21%2Cf23%2Cf24%2Cf25%2Cf22%2Cf11%2Cf62%2Cf128%2Cf136%2Cf115%2Cf152 (Caused by ProxyError('Unable to connect to proxy',  |

## Cross-source Validation

- validation status: baostock_available_akshare_unavailable
- Baostock fallback status: success
- comparison count: 0

Baostock remains available as the A-share daily fallback. No output enters formal trusted consumption.
