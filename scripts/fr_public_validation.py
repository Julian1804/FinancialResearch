"""Run bounded offline public-source smoke checks with disposable FR roots.

These checks do not validate full product behavior, financial data, provider
availability, release acceptance, or publication readiness.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


COMMANDS = {
    "smoke": ("tests.test_public_source_smoke",),
}


def validation_environment(root: Path) -> dict[str, str]:
    """Discard inherited FR path/provider overrides for this test process only."""
    environment = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("FR_", "FINANCIAL_RESEARCH_"))
    }
    environment.update({
        "FR_TEST_ISOLATION_REQUIRED": "1",
        "FR_TEST_STORAGE_ROOT": str(root),
        "FR_LOCAL_STORAGE_ROOT": str(root / "local"),
        "FR_NAS_ROOT": str(root / "nas"),
        "FR_INSTALLATION_BOOTSTRAP_PATH": str(root / "installation.json"),
        "FINANCIAL_RESEARCH_RUNTIME_ROOT": str(root / "runtime"),
        "FINANCIAL_RESEARCH_DATA_ROOT": str(root / "data"),
        "PYTHONNOUSERSITE": "1",
    })
    return environment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=tuple(COMMANDS))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="fr-public-validation-") as temporary:
        root = Path(temporary)
        print(json.dumps({
            "event": "public_validation_test_root",
            "suite": args.suite,
            "root": str(root),
            "ownership": "disposable_test_only",
        }), flush=True)
        result = subprocess.run(
            [sys.executable, "-m", "unittest", *COMMANDS[args.suite]],
            env=validation_environment(root),
            check=False,
        )
        artifacts = sorted([
            {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size}
            for path in root.rglob("*") if path.is_file()
        ], key=lambda row: row["path"])
        print(json.dumps({
            "event": "public_validation_test_artifacts",
            "suite": args.suite,
            "root": str(root),
            "exit_code": result.returncode,
            "artifacts": artifacts,
        }), flush=True)
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
