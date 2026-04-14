from __future__ import annotations

from typing import Dict, Any, List, Tuple
import configparser
import json
import os
import tomllib

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


def _read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def yaml_parse_ok(path: str) -> Tuple[bool, str]:
    if yaml is None:
        return False, "pyyaml not installed"
    try:
        yaml.safe_load(_read_text(path))
        return True, "yaml parse ok"
    except Exception as e:
        return False, f"yaml parse failed: {e}"


def json_parse_ok(path: str) -> Tuple[bool, str]:
    try:
        json.loads(_read_text(path))
        return True, "json parse ok"
    except Exception as e:
        return False, f"json parse failed: {e}"


def toml_parse_ok(path: str) -> Tuple[bool, str]:
    try:
        with open(path, "rb") as f:
            tomllib.load(f)
        return True, "toml parse ok"
    except Exception as e:
        return False, f"toml parse failed: {e}"


def ini_parse_ok(path: str) -> Tuple[bool, str]:
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(_read_text(path))
        return True, "ini parse ok"
    except Exception as e:
        return False, f"ini parse failed: {e}"


def python_compile_ok(path: str) -> Tuple[bool, str]:
    try:
        source = _read_text(path)
        compile(source, path, "exec")
        return True, "python syntax ok"
    except Exception as e:
        return False, f"python syntax failed: {e}"


def file_exists(repo: str, relpath: str) -> bool:
    return os.path.exists(os.path.join(repo, relpath))


def _check_spec_for_path(relpath: str) -> Tuple[str, Any] | None:
    lower = relpath.lower()
    if lower.endswith((".yml", ".yaml")):
        return ("yaml_parse", yaml_parse_ok)
    if lower.endswith(".json"):
        return ("json_parse", json_parse_ok)
    if lower.endswith(".toml"):
        return ("toml_parse", toml_parse_ok)
    if lower.endswith((".cfg", ".ini")):
        return ("ini_parse", ini_parse_ok)
    if lower.endswith(".py"):
        return ("python_compile", python_compile_ok)
    return None


def basic_static_validation(repo: str, touched_paths: List[str]) -> Dict[str, Any]:
    results: Dict[str, Any] = {"checks": []}
    for relpath in touched_paths:
        spec = _check_spec_for_path(relpath)
        if spec is None:
            continue
        check_type, checker = spec
        full_path = os.path.join(repo, relpath)
        if not os.path.exists(full_path):
            results["checks"].append(
                {
                    "type": check_type,
                    "path": relpath,
                    "ok": False,
                    "msg": "file missing after patch application",
                }
            )
            continue
        ok, msg = checker(full_path)
        results["checks"].append({"type": check_type, "path": relpath, "ok": ok, "msg": msg})
    return results
