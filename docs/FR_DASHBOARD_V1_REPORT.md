# FR Dashboard v1 Report

Generated: 2026-05-20T08:16:05Z

Dashboard v1 acceptance hardening completed.

- UI implementation: new `frontend_web/src/dashboard_v1`, not Streamlit.
- UX refinement: dark financial research dashboard cards, real macro/asset summaries and report download controls.
- UI operability: semi_dynamic_local_action_layer.
- Action server: `scripts/run_dashboard_v1_action_server.py`.
- 600519 E2E smoke: success.
- Custom topic E2E smoke: success.
- Report upload smoke: success.
- Strengthened UI smoke: passed.
- legacy_streamlit_used: false.
- no_openai_api_called: true.
- trusted_consumption_affected: false.

Start:

```powershell
cd D:\workspace\FinancialResearch
D:\workspace\envs\financial_research_backend\Scripts\python.exe scripts\run_dashboard_v1_action_server.py --host 127.0.0.1 --port 5188
```

Open: http://127.0.0.1:5188/
