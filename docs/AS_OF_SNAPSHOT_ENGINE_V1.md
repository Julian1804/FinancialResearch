# As-of Snapshot Engine v1

Generated: 2026-05-20T04:59:09Z

The engine accepts research object fields, selected data categories, time_mode, date window,
fiscal_year/reporting_period and `as_of_check_enabled`.

Default filter is publish_date. Missing publish_date and future publish_date are separated from
included items.

Sample counts:

```json
{
  "included": 4,
  "excluded": 1,
  "missing_publish_date_review": 25,
  "excluded_due_to_future_publish_date": 4
}
```

All outputs remain candidate/research evidence and do not enter formal trusted consumption.
