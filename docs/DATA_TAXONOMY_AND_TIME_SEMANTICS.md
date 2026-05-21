# Data Taxonomy and Time Semantics

Generated: 2026-05-21T10:28:19Z

Default time mode is `publish_date`; `as_of_check_enabled` defaults to true.

Supported time modes:

- publish_date
- data_period
- fiscal_year
- reporting_period
- announcement_date
- event_date
- analysis_time
- ingestion_time

Rules:

- Missing publish_date items go to `missing_publish_date_review`.
- publish_date later than window_end goes to `excluded_due_to_future_publish_date`.
- fiscal_year and reporting_period can locate financial reports, but as-of safety still checks publish_date.
- If as_of_check_enabled is false, report output is marked `not_asof_safe`.

Sample snapshot counts:

```json
{
  "included": 20,
  "excluded": 7,
  "missing_publish_date_review": 44,
  "excluded_due_to_future_publish_date": 4
}
```
