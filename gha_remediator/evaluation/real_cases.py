from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from ..ingestion.github_actions import load_github_actions_logs


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _combined_log_text(entries: List[Dict[str, Any]]) -> str:
    ordered = sorted(entries, key=lambda item: item.get("path", ""))
    parts: List[str] = []
    for entry in ordered:
        parts.append(f"===== {entry.get('path', 'log')} =====")
        parts.append(entry.get("content", ""))
    return "\n".join(parts)


def export_real_case_stub(
    *,
    repo: str,
    run_id: int,
    out_dir: str = "dataset/real_cases/cases",
) -> Dict[str, str]:
    entries = load_github_actions_logs(repo=repo, run_id=run_id)
    if not entries:
        raise RuntimeError("No logs were returned for the requested run.")

    metadata = entries[0].get("metadata", {})
    case_slug = _slugify(f"{repo}_{run_id}")
    case_dir = Path(out_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    log_path = case_dir / f"{case_slug}.log"
    annotation_path = case_dir / f"{case_slug}.json"

    log_path.write_text(_combined_log_text(entries), encoding="utf-8")

    annotation = {
        "case_id": case_slug,
        "repo": repo,
        "run_id": run_id,
        "workflow_name": metadata.get("workflow_name"),
        "workflow_path": None,
        "failure_class": None,
        "root_cause": "",
        "evidence_lines": [],
        "notes": "",
        "log_path": str(log_path),
        "html_url": metadata.get("html_url"),
    }
    annotation_path.write_text(json.dumps(annotation, indent=2), encoding="utf-8")

    return {
        "log_path": str(log_path),
        "annotation_path": str(annotation_path),
    }
