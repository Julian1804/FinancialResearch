# AKShare Deep Diagnosis Report

## Environment

- Python: `3.10.11 (tags/v3.10.11:7d4cc5a, Apr  5 2023, 00:38:17) [MSC v.1929 64 bit (AMD64)]`
- AKShare: `1.18.62` latest available: `1.18.62`
- requests: `2.33.1`
- urllib3: `2.6.3`
- curl_cffi: `0.15.0`
- proxy environment: `{"HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "", "NO_PROXY": ""}`

## AKShare Source Inspection

- source file: `D:\workspace\envs\financial_research_backend\Lib\site-packages\akshare\stock_feature\stock_hist_em.py`
- function first line: 952
- URL: `https://push2his.eastmoney.com/api/qt/stock/kline/get`
- client: `requests.get(url, params=params, timeout=timeout)`
- session: False
- timeout: function argument timeout, defaults to None
- failure layer: kline_get_network_layer_before_json_parse_when RemoteDisconnected/empty response occurs

## Minimal Reproduction Matrix

- items: 27
- success: 0
- failed: 27

```json
{
  "akshare_stock_zh_a_hist": {
    "success": 0,
    "failed": 3
  },
  "requests_https_headers": {
    "success": 0,
    "failed": 3
  },
  "requests_https_headers_trust_env_false": {
    "success": 0,
    "failed": 3
  },
  "requests_http_headers": {
    "success": 0,
    "failed": 3
  },
  "urllib_https_headers": {
    "success": 0,
    "failed": 3
  },
  "curl_https_default": {
    "success": 0,
    "failed": 3
  },
  "curl_https_http1_tls12_compressed_ipv4": {
    "success": 0,
    "failed": 3
  },
  "curl_http_default": {
    "success": 0,
    "failed": 3
  },
  "curl_cffi_chrome": {
    "success": 0,
    "failed": 3
  }
}
```

Conclusion: all tested clients failed or returned no klines; issue is network/upstream/TLS layer, not AKShare field mapping

## Patch Attempts

- repair status: partially_repaired
- root cause: Eastmoney push2his network/TLS/upstream disconnect affects AKShare and direct clients; failure occurs before JSON parse and is not fixed by headers, trust_env=False, curl, HTTP/1.1/TLS1.2, or curl_cffi in this environment.
- Eastmoney-backed `stock_zh_a_hist` stable: False
- AKShare alternative daily source available: True

Patch attempts remain candidate-only and do not affect formal trusted consumption.
