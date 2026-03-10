from __future__ import annotations

from typing import Dict, Any, List, Tuple
import os
import json

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

def yaml_parse_ok(path: str) -> Tuple[bool, str]:
    if yaml is None:
        return False, "pyyaml not installed"
    try:
        with open(path, "r", encoding="utf-8") as f:
            yaml.safe_load(f)
        return True, "yaml parse ok"
    except Exception as e:
        return False, f"yaml parse failed: {e}"

def file_exists(repo: str, relpath: str) -> bool:
    return os.path.exists(os.path.join(repo, relpath))

def basic_static_validation(repo: str, touched_paths: List[str]) -> Dict[str, Any]:
    results: Dict[str, Any] = {"checks": []}
    for p in touched_paths:
        if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml")):
            ok, msg = yaml_parse_ok(os.path.join(repo, p))
            results["checks"].append({"type": "yaml_parse", "path": p, "ok": ok, "msg": msg})
    return results
