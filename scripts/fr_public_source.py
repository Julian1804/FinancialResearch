"""Check the public application import closure and required static resources."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


APPLICATION_RESOURCE_FILES = frozenset({
    "config/fr_app_registry.json",
    "config/fr_governed_component_registry.json",
    "config/fr_authoritative_subject_registry_schema.json",
    "config/fr_dashboard_registry.json",
    "config/fr_first_install_source_contract.json",
    "config/fr_module_registry.json",
    "config/fr_project_registry.json",
    "config/fr_storage_profile.json",
    "config/metrics_registry.json",
})

def _module_candidates(module: str) -> tuple[str, ...]:
    base = module.replace(".", "/")
    return (f"{base}.py", f"{base}/__init__.py")


def _existing_module_path(root: Path, module: str) -> str | None:
    return next((path for path in _module_candidates(module) if (root / path).is_file()), None)


def _package_initializers(root: Path, path: str) -> set[str]:
    result: set[str] = set()
    parent = Path(path).parent
    while parent.as_posix().startswith("backend"):
        initializer = (parent / "__init__.py").as_posix()
        if (root / initializer).is_file():
            result.add(initializer)
        if parent.as_posix() == "backend":
            break
        parent = parent.parent
    return result


def backend_import_closure(
    root: Path,
    entry_modules: tuple[str, ...] = ("backend.app.main",),
) -> frozenset[str]:
    """Return all repo-local backend modules reachable from the entry modules."""
    pending = list(entry_modules)
    visited_modules: set[str] = set()
    selected: set[str] = set()
    while pending:
        module = pending.pop()
        if module in visited_modules or not module.startswith("backend"):
            continue
        visited_modules.add(module)
        path = _existing_module_path(root, module)
        if path is None:
            continue
        selected.add(path)
        selected.update(_package_initializers(root, path))
        tree = ast.parse((root / path).read_text(encoding="utf-8"), filename=path)
        package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names if alias.name.startswith("backend"))
            elif isinstance(node, ast.ImportFrom):
                imported = node.module or ""
                if node.level:
                    parts = package.split(".")
                    imported = ".".join(parts[: len(parts) - node.level + 1] + ([imported] if imported else []))
                if not imported.startswith("backend"):
                    continue
                pending.append(imported)
                for alias in node.names:
                    candidate = f"{imported}.{alias.name}"
                    if _existing_module_path(root, candidate):
                        pending.append(candidate)
    return frozenset(selected)


def application_source_files(root: Path) -> frozenset[str]:
    missing = sorted(path for path in APPLICATION_RESOURCE_FILES if not (root / path).is_file())
    if missing:
        raise FileNotFoundError(f"application resource files are missing: {missing}")
    return backend_import_closure(root) | APPLICATION_RESOURCE_FILES


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check-closure",))
    args = parser.parse_args()
    if args.action == "check-closure":
        root = Path(__file__).resolve().parents[1]
        selected = application_source_files(root)
        print(json.dumps({"entry_module": "backend.app.main",
                          "selected_file_count": len(selected),
                          "required_resource_count": len(APPLICATION_RESOURCE_FILES)},
                         sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
