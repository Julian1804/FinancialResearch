from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.clients.parse_lab_client import ParseLabClient  # noqa: E402


def main() -> int:
    client = ParseLabClient()
    health = client.get_health()
    tasks = client.list_tasks()
    result = {
        "base_url": client.base_url,
        "health": health,
        "tasks": {
            "keys": sorted(tasks.keys()),
            "count": tasks.get("count"),
            "total": tasks.get("total"),
            "task_sample_size": len(tasks.get("tasks") or []),
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
