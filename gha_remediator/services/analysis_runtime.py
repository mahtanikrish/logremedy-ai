from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..app_settings import load_app_settings, resolve_github_token
from ..ingestion.github_actions import combine_github_log_entries, load_github_actions_logs
from ..runtime_factory import build_remediator, describe_kb, load_kb_for_settings, normalize_repo_path


def run_synthetic_analysis(log_path: str, repo: str, model: str) -> tuple[Dict[str, Any], str]:
    raw_log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    return run_synthetic_analysis_text(raw_log_text=raw_log_text, repo=repo, model=model), raw_log_text


def run_synthetic_analysis_text(raw_log_text: str, repo: str, model: str) -> Dict[str, Any]:
    repo = normalize_repo_path(repo)
    settings = load_app_settings()
    return build_remediator(model=model, settings=settings, max_output_tokens=2200).run(
        raw_log_text=raw_log_text,
        repo=repo,
        replay=False,
        job=None,
    )


def run_github_analysis(repo_name: str, run_id: int | None, verify_repo: str, model: str) -> tuple[Dict[str, Any], int | None, str]:
    settings = load_app_settings()
    token, _token_source = resolve_github_token(settings=settings)
    verify_repo = normalize_repo_path(verify_repo)
    entries = load_github_actions_logs(
        repo=repo_name,
        run_id=run_id,
        limit=1,
        token=token,
    )
    raw_log_text = combine_github_log_entries(entries)
    active_run_id = entries[0].get("metadata", {}).get("run_id")
    result = build_remediator(model=model, settings=settings, max_output_tokens=2200).run(
        raw_log_text=raw_log_text,
        repo=verify_repo,
        replay=False,
        job=None,
    )
    return result, active_run_id, raw_log_text
