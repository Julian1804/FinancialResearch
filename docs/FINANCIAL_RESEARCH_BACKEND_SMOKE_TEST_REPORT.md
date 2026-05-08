# FinancialResearch Backend Smoke Test Report

Generated at: 2026-05-03

## Scope

This smoke test only validates the new FinancialResearch FastAPI backend health endpoint.

Not performed:

- No Parse Lab connectivity test
- No financial report parsing
- No FinancialResearch analysis pipeline
- No parser environment changes
- No parse_lab changes
- No commit or push

## Python Environment

Virtual environment path:

```text
D:\workspace\envs\financial_research_backend
```

The environment did not exist before this test and was created with:

```text
python -m venv D:\workspace\envs\financial_research_backend
```

Python:

```text
Python 3.10.11
```

## Installed Requirements

Installed from:

```text
D:\workspace\FinancialResearch\requirements\backend-api.txt
```

Requested packages:

```text
fastapi
uvicorn
pydantic
requests
python-dotenv
```

Observed installed packages:

```text
fastapi==0.136.1
uvicorn==0.46.0
pydantic==2.13.3
requests==2.33.1
python-dotenv==1.2.2
```

Transitive packages were installed by pip in the same virtual environment.

## Startup Command

Started from:

```text
D:\workspace\FinancialResearch
```

Command:

```text
D:\workspace\envs\financial_research_backend\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8030
```

Listening endpoint:

```text
http://127.0.0.1:8030
```

Observed listener process:

```text
127.0.0.1:8030
```

## Health Check

Request:

```text
GET http://127.0.0.1:8030/api/health
```

Response:

```json
{"status":"ok","service":"financial_research_backend"}
```

Result: passed.

## Warnings

- Pip reported that a newer pip release is available. This was not upgraded.
- No Parse Lab endpoint was called.
- No business route was exercised.

## Next Step Readiness

The backend health smoke test passed.

It is safe to proceed to a separate Parse Lab client connectivity test, limited to HTTP connectivity and task metadata calls, without running financial parsing or analysis flows.
