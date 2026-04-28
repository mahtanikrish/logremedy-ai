from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple


DEFAULT_SETTINGS_PATH = Path.home() / ".gha-remediator" / "web-settings.json"


@dataclass(frozen=True)
class AppSettings:
    knowledge_base_path: str = ""
    env_file_path: str = ""


def settings_path() -> Path:
    override = os.environ.get("GHA_REMEDIATOR_SETTINGS_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_SETTINGS_PATH


def load_app_settings() -> AppSettings:
    path = settings_path()
    if not path.exists():
        return AppSettings()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid settings file JSON at {path}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid settings payload at {path}")

    return AppSettings(
        knowledge_base_path=str(data.get("knowledge_base_path", "")).strip(),
        env_file_path=str(data.get("env_file_path", "")).strip(),
    )


def save_app_settings(settings: AppSettings) -> AppSettings:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
    return settings


def parse_env_file(path: str) -> Dict[str, str]:
    env_path = Path(path).expanduser().resolve()
    values: Dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_github_token(settings: Optional[AppSettings] = None,environ: Optional[Dict[str, str]] = None,) -> Tuple[Optional[str], str]:
    settings = settings or load_app_settings()
    environ = environ or os.environ

    env_token = environ.get("GITHUB_TOKEN", "").strip()
    if env_token:
        return env_token, "environment"

    env_file_path = settings.env_file_path.strip()
    if env_file_path:
        path = Path(env_file_path).expanduser().resolve()
        if path.exists() and path.is_file():
            token = parse_env_file(str(path)).get("GITHUB_TOKEN", "").strip()
            if token:
                return token, "env_file"

    return None, "missing"


def settings_payload(settings: Optional[AppSettings] = None) -> Dict[str, object]:
    settings = settings or load_app_settings()
    token, token_source = resolve_github_token(settings=settings)
    env_path = settings.env_file_path.strip()
    env_file = Path(env_path).expanduser().resolve() if env_path else None
    env_file_exists = bool(env_file and env_file.exists() and env_file.is_file())

    kb_path = settings.knowledge_base_path.strip()
    kb_file = Path(kb_path).expanduser().resolve() if kb_path else None
    kb_exists = bool(kb_file and kb_file.exists())

    return {
        "settings": {
            "knowledgeBasePath": settings.knowledge_base_path,
            "envFilePath": settings.env_file_path,
        },
        "settingsFilePath": str(settings_path()),
        "knowledgeBase": {
            "configured": bool(kb_path),
            "path": str(kb_file) if kb_file else "",
            "exists": kb_exists,
        },
        "githubToken": {
            "present": bool(token),
            "source": token_source,
            "envFilePath": str(env_file) if env_file else "",
            "envFileExists": env_file_exists,
        },
    }
