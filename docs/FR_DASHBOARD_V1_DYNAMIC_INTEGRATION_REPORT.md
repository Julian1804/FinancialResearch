# FR Dashboard v1 Dynamic Integration Report

Generated: 2026-05-20T07:40:34Z

Operability level: semi_dynamic_local_action_layer.

The UI is no longer only marker-verified. The local action layer supports:

- GET dashboard summary
- POST generate_asof_snapshot
- POST generate_statistical_report
- POST classify_uploaded_report
- GET research_workspace
- GET report paths

600519 E2E: success counts={"included": 20, "excluded": 7, "missing_publish_date_review": 26, "excluded_due_to_future_publish_date": 0}

Custom topic E2E: success counts={"included": 16, "excluded": 6, "missing_publish_date_review": 29, "excluded_due_to_future_publish_date": 0}

Report upload smoke: success schema_valid=True

UI smoke: passed actions=5

legacy_streamlit_used = false
no_openai_api_called = true
trusted_consumption_affected = false

Dynamic audit items: 9
