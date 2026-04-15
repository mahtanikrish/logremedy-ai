from __future__ import annotations

from typing import Dict, Any, Callable, List, Tuple
import configparser
import json
import os
import subprocess
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


def shell_syntax_ok(path: str) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            ["bash", "-n", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "shell syntax ok"
        stderr = result.stderr.strip()[-200:]
        return False, f"shell syntax failed: {stderr or 'bash -n returned non-zero'}"
    except Exception as e:
        return False, f"shell syntax failed: {e}"


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
    if lower.endswith(".sh"):
        return ("shell_syntax", shell_syntax_ok)
    return None


def yaml_available() -> bool:
    return yaml is not None


def _run_check(
    relpath: str,
    check_type: str,
    checker: Callable[[str], Tuple[bool, str]],
    full_path: str,
) -> Dict[str, Any]:
    if check_type == "yaml_parse" and yaml is None:
        return {
            "type": check_type,
            "path": relpath,
            "ok": None,
            "available": False,
            "msg": "pyyaml not installed",
        }
    ok, msg = checker(full_path)
    return {
        "type": check_type,
        "path": relpath,
        "ok": ok,
        "available": True,
        "msg": msg,
    }


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
                    "available": True,
                    "msg": "file missing after patch application",
                }
            )
            continue
        results["checks"].append(_run_check(relpath, check_type, checker, full_path))
    return results
