from __future__ import annotations

import json
import sys
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_generate_morningstar_report_endpoint() -> None:
    from scripts.run_dashboard_v1_action_server import run_server

    server_thread = threading.Thread(target=lambda: run_server("127.0.0.1", 5199), daemon=True)
    server_thread.start()
    time.sleep(1.5)

    conn = HTTPConnection("127.0.0.1", 5199)
    conn.request("POST", "/api/dashboard/generate_morningstar_report", body=json.dumps({}), headers={"Content-Type": "application/json"})
    response = conn.getresponse()
    assert response.status == 200
    payload = json.loads(response.read().decode("utf-8"))
    assert payload["status"] == "ok"
    assert payload["action"] == "generate_morningstar_report"
    assert payload["api_calls_made"] == 0
    assert payload["no_openai_api_called"] is True
    assert payload["formal_trusted_consumption"] is False
    assert payload["tna_enf_blocked"] is True
    assert payload["us_equity_standalone_excluded"] is True
    outputs = payload["outputs"]
    assert outputs["morningstar_workspace_index"]
    assert outputs["morningstar_statistical_report"]
    assert outputs["morningstar_analysis_packet"]
    assert outputs["morningstar_evidence_boundary"]
    conn.close()
    print("morningstar dashboard action server endpoint test passed")


if __name__ == "__main__":
    test_generate_morningstar_report_endpoint()
