# Commodity Data Model v1

Generated: 2026-05-20T07:36:53Z

Commodity schema now distinguishes `price_type`, `exchange`, `commodity_category`, and instrument identity.

Current upgraded series: 10

Price type counts:

```json
{
  "benchmark": 10
}
```

Exchange counts:

```json
{
  "World Bank": 10
}
```

World Bank Pink Sheet series are marked benchmark/average-price style evidence, not exchange futures.
