# Legacy Streamlit Archive Note

Generated: 2026-05-20T06:18:11Z

Legacy Streamlit files and reports are archived references only. Dashboard v1 does not use Streamlit.

Allowed legacy uses:

- Historical issue review.
- Parser comparison background.
- Migration lessons.

Not allowed:

- Treating a legacy Streamlit URL as Dashboard v1 validation.
- Building new Dashboard v1 pages on Streamlit.
- Passing UI smoke by checking old route status codes.

Dashboard v1 guard:

- legacy_streamlit_used = false
- old_ui_false_positive_guard = true
