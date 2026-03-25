from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..ingestion.github_actions import load_github_actions_logs
from ..llm.base import LLMConfig
from ..llm.github_models_client import GitHubModelsClient
from ..pipeline import GHARemediator
from ..rag import Doc, KnowledgeBase


def default_kb() -> KnowledgeBase:
    return KnowledgeBase(
        [
            Doc(
                "py-missing-module",
                "Python: ModuleNotFoundError in CI",
                "If CI fails with ModuleNotFoundError, ensure the dependency is listed in requirements/pyproject and installed in the workflow. Prefer pinning known-good versions.",
            ),
            Doc(
                "gha-yaml",
                "GitHub Actions: YAML workflow invalid",
                "Validate YAML syntax and check action inputs. Ensure uses: references exist and step keys are correctly indented.",
            ),
            Doc(
                "node-build",
                "Node: build failed",
                "Run npm ci before build. Ensure correct node-version and that package-lock matches. Check tsc errors and tsconfig.",
            ),
        ]
    )


def build_remediator(model: str) -> GHARemediator:
    llm = GitHubModelsClient()
    llm_cfg = LLMConfig(model=model, max_output_tokens=1400, temperature=0)
    return GHARemediator(kb=default_kb(), llm=llm, llm_cfg=llm_cfg)


def combine_github_logs(entries: List[Dict[str, Any]]) -> str:
    ordered = sorted(entries, key=lambda item: item.get("path", ""))
    parts: List[str] = []
    for entry in ordered:
        parts.append(f"===== {entry.get('path', 'log')} =====")
        parts.append(entry.get("content", ""))
    return "\n".join(parts)


def run_synthetic_analysis(log_path: str, repo: str, model: str) -> tuple[Dict[str, Any], str]:
    raw_log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    result = build_remediator(model).run(
        raw_log_text=raw_log_text,
        repo=repo,
        replay=False,
        job=None,
    )
    return result, raw_log_text


def run_github_analysis(repo_name: str, run_id: int | None, verify_repo: str, model: str) -> tuple[Dict[str, Any], int | None, str]:
    entries = load_github_actions_logs(
        repo=repo_name,
        run_id=run_id,
        limit=1,
        token=None,
    )
    raw_log_text = combine_github_logs(entries)
    active_run_id = entries[0].get("metadata", {}).get("run_id")
    result = build_remediator(model).run(
        raw_log_text=raw_log_text,
        repo=verify_repo,
        replay=False,
        job=None,
    )
    return result, active_run_id, raw_log_text
