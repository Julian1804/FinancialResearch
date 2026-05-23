"""Test Morningstar Token UI + local_secrets management."""
import json, os, sys, subprocess, tempfile
from pathlib import Path

PROJECT_ROOT = Path(r'D:\workspace\FinancialResearch')
sys.path.insert(0, str(PROJECT_ROOT))

SECRETS_PATH = PROJECT_ROOT / "config" / "local_secrets.json"
GITIGNORE_PATH = PROJECT_ROOT / ".gitignore"

passed = 0; failed = 0
def ck(name, cond):
    global passed, failed
    if cond: print(f"PASS: {name}"); passed += 1
    else: print(f"FAIL: {name}"); failed += 1

# 1. local_secrets.json covered by gitignore
gitignore = GITIGNORE_PATH.read_text(encoding="utf-8") if GITIGNORE_PATH.exists() else ""
ck("gitignore_exists", GITIGNORE_PATH.exists())
ck("gitignore_covers_local_secrets", "local_secrets.json" in gitignore.lower() or "**/local_secrets.json" in gitignore)

# 2. local_secrets.json exists and has structure
secrets = {}
if SECRETS_PATH.exists():
    secrets = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
    ck("local_secrets_exists", True)
    ck("morningstar_key", "morningstar" in secrets)
    ck("md_auth_token_present", bool(secrets.get("morningstar", {}).get("md_auth_token")))
    ck("account_hint_present", "account_hint" in secrets.get("morningstar", {}))
else:
    ck("local_secrets_exists", False)
    ck("morningstar_key", True)  # skip on missing file
    ck("md_auth_token_present", True)
    ck("account_hint_present", True)

# 3. Token NOT leaked in test output (only real-looking JWT with long payload)
test_content = Path(__file__).read_text(encoding="utf-8")
# Count "eyJ" occurrences that look like real tokens (long base64) vs test fixtures
import re
real_jwt_patterns = len(re.findall(r'eyJ[A-Za-z0-9_-]{100,}', test_content))
ck("no_token_in_test", real_jwt_patterns == 0)

# 4. Verify action server has token endpoints
server_code = (PROJECT_ROOT / "scripts" / "run_dashboard_v1_action_server.py").read_text(encoding="utf-8")
ck("token_save_endpoint_in_server", "_handle_token_save" in server_code)
ck("token_status_endpoint_in_server", "_handle_token_status" in server_code)
ck("token_mask_in_server", "_mask_token" in server_code)

# 5. Frontend panel exists
panel_path = PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1" / "morningstar_token_panel.html"
ck("token_panel_html_exists", panel_path.exists())
if panel_path.exists():
    panel_html = panel_path.read_text(encoding="utf-8")
    ck("panel_has_save_button", "saveToken" in panel_html)
    ck("panel_has_status_refresh", "refreshStatus" in panel_html)
    ck("panel_has_masking", "maskToken" in panel_html)
    # Must not contain sample real token
    ck("panel_no_jwt_leak", "eyJ" not in panel_html)

# 6. git check - local_secrets NOT tracked
result = subprocess.run(["git", "-C", str(PROJECT_ROOT), "ls-files", "--error-unmatch", "config/local_secrets.json"], capture_output=True, text=True)
ck("local_secrets_not_git_tracked", result.returncode != 0)

# 7. Runtime summary must not contain token
status_dir = PROJECT_ROOT / "runtime" / "morningstar_token_status"
if status_dir.exists():
    status_file = status_dir / "token_status_latest.json"
    if status_file.exists():
        status_json = json.loads(status_file.read_text(encoding="utf-8"))
        ck("runtime_status_no_token", "md_auth_token" not in status_json or len(str(status_json.get("md_auth_token",""))) < 10)

# 8. Token save simulation
def simulate_token_logic():
    """Simulate the save logic from action server."""
    import json, base64 as b64
    from datetime import datetime, timezone, timedelta

    test_token = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjk5OTk5OTk5OTl9.test"
    test_hint = "test@morningstar.com"

    # Simulate save
    saved_at = datetime.now(timezone.utc).isoformat()
    secrets_sim = {
        "morningstar": {
            "md_auth_token": test_token,
            "token_saved_at": saved_at,
            "token_expires_hours": 24,
            "token_source": "dashboard_manual_input",
            "account_hint": test_hint
        }
    }

    # Verify save structure
    assert secrets_sim["morningstar"]["token_saved_at"] == saved_at
    assert secrets_sim["morningstar"]["token_expires_hours"] == 24
    assert secrets_sim["morningstar"]["token_source"] == "dashboard_manual_input"

    # Verify masking
    masked = "****" + test_token[-4:]
    assert masked == "****test"

    # Verify expiry calculation
    saved_dt = datetime.fromisoformat(saved_at)
    expires_dt = saved_dt + timedelta(hours=24)
    remaining = max(0, (expires_dt - datetime.now(timezone.utc)).total_seconds())
    assert remaining > 0  # Just saved, should have time

    # Verify JWT decoding
    parts = test_token.split(".")
    payload = parts[1]; pad = 4 - len(payload) % 4
    if pad != 4: payload += "=" * pad
    decoded = json.loads(b64.urlsafe_b64decode(payload))
    assert decoded.get("exp") == 9999999999

    # Verify status does NOT return full token
    status = {
        "token_available": True,
        "masked_token": masked,
        "token_saved_at": saved_at,
        "estimated_expires_at": expires_dt.isoformat(),
    }
    assert status["masked_token"] != test_token
    assert len(status["masked_token"]) < len(test_token)
    assert test_token not in status["masked_token"][:4]  # first 4 chars are ****

    return True

ck("simulate_token_save_logic", simulate_token_logic())

# 9. Dashboard sample data must not contain token
sample_path = PROJECT_ROOT / "runtime" / "dashboard_v1" / "dashboard_v1_frontend" / "dashboard_v1_sample_data.json"
if sample_path.exists():
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    sample_str = json.dumps(sample)
    ck("sample_data_no_token_leak", "eyJ" not in sample_str)

print(f"\nResults: {passed} passed, {failed} failed, {passed + failed} total")
if failed > 0: sys.exit(1)
