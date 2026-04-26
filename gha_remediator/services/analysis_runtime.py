from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..app_settings import AppSettings, load_app_settings, resolve_github_token
from ..ingestion.github_actions import load_github_actions_logs
from ..llm.base import LLMConfig
from ..llm.github_models_client import GitHubModelsClient
from ..pipeline import GHARemediator
from ..rag import Doc, KnowledgeBase


def normalize_repo_path(repo: str) -> str:
    repo = repo.strip()
    if not repo:
        return ""
    if repo.startswith("Users/"):
        repo = "/" + repo
    return str(Path(repo).expanduser().resolve())


def _default_docs() -> List[Doc]:
    return [
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


def default_kb() -> KnowledgeBase:
    return KnowledgeBase(_default_docs())


def _doc_from_mapping(item: Dict[str, Any], fallback_id: str, source: str) -> Doc:
    return Doc(
        doc_id=str(item.get("doc_id") or item.get("id") or fallback_id),
        title=str(item.get("title") or fallback_id),
        text=str(item.get("text") or item.get("content") or ""),
        source=str(item.get("source") or source),
    )


def _load_docs_from_json_payload(payload: Any, source: str) -> List[Doc]:
    items = payload.get("docs") if isinstance(payload, dict) and "docs" in payload else payload
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        raise RuntimeError(f"Knowledge base file must contain a list of docs or a top-level 'docs' list: {source}")

    docs: List[Doc] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            docs.append(_doc_from_mapping(item, fallback_id=f"doc-{index}", source=source))
        elif isinstance(item, str):
            docs.append(Doc(doc_id=f"doc-{index}", title=f"Doc {index}", text=item, source=source))
    return [doc for doc in docs if doc.text.strip()]


def _load_docs_from_file(path: Path) -> List[Doc]:
    suffix = path.suffix.lower()
    source = str(path)
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return _load_docs_from_json_payload(payload, source=source)
    if suffix == ".jsonl":
        docs: List[Doc] = []
        for index, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                docs.append(_doc_from_mapping(payload, fallback_id=f"{path.stem}-{index}", source=source))
            elif isinstance(payload, str):
                docs.append(Doc(doc_id=f"{path.stem}-{index}", title=f"{path.stem} {index}", text=payload, source=source))
        return [doc for doc in docs if doc.text.strip()]

    text = path.read_text(encoding="utf-8")
    return [Doc(doc_id=path.stem, title=path.stem.replace("_", " "), text=text, source=source)] if text.strip() else []


def _iter_kb_files(root: Path) -> Iterable[Path]:
    supported = {".json", ".jsonl", ".txt", ".md"}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in supported:
            yield path


def load_kb_for_settings(settings: AppSettings | None = None) -> KnowledgeBase:
    settings = settings or load_app_settings()
    kb_path = settings.knowledge_base_path.strip()
    if not kb_path:
        return default_kb()

    root = Path(kb_path).expanduser().resolve()
    if not root.exists():
        raise RuntimeError(f"Knowledge base path does not exist: {root}")

    docs: List[Doc] = []
    if root.is_dir():
        for file_path in _iter_kb_files(root):
            docs.extend(_load_docs_from_file(file_path))
    else:
        docs.extend(_load_docs_from_file(root))

    if not docs:
        raise RuntimeError(f"No knowledge base documents found at {root}")

    return KnowledgeBase(docs)


def describe_kb(settings: AppSettings | None = None) -> Dict[str, Any]:
    settings = settings or load_app_settings()
    kb_path = settings.knowledge_base_path.strip()
    if not kb_path:
        return {"configured": False, "source": "default", "docCount": len(_default_docs()), "error": None}

    root = Path(kb_path).expanduser().resolve()
    if not root.exists():
        return {"configured": True, "source": "path", "docCount": 0, "error": f"Knowledge base path does not exist: {root}"}

    try:
        kb = load_kb_for_settings(settings)
    except Exception as exc:
        return {"configured": True, "source": "path", "docCount": 0, "error": str(exc)}
    return {"configured": True, "source": "path", "docCount": len(kb.docs), "error": None}


def build_remediator(model: str, settings: AppSettings | None = None) -> GHARemediator:
    settings = settings or load_app_settings()
    token, _token_source = resolve_github_token(settings=settings)
    llm = GitHubModelsClient(token=token)
    llm_cfg = LLMConfig(model=model, max_output_tokens=2200, temperature=0)
    return GHARemediator(kb=load_kb_for_settings(settings), llm=llm, llm_cfg=llm_cfg)


def combine_github_logs(entries: List[Dict[str, Any]]) -> str:
    ordered = sorted(entries, key=lambda item: item.get("path", ""))
    parts: List[str] = []
    for entry in ordered:
        parts.append(f"===== {entry.get('path', 'log')} =====")
        parts.append(entry.get("content", ""))
    return "\n".join(parts)


def run_synthetic_analysis(log_path: str, repo: str, model: str) -> tuple[Dict[str, Any], str]:
    raw_log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    return run_synthetic_analysis_text(raw_log_text=raw_log_text, repo=repo, model=model), raw_log_text


def run_synthetic_analysis_text(raw_log_text: str, repo: str, model: str) -> Dict[str, Any]:
    repo = normalize_repo_path(repo)
    settings = load_app_settings()
    return build_remediator(model, settings=settings).run(
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
    raw_log_text = combine_github_logs(entries)
    active_run_id = entries[0].get("metadata", {}).get("run_id")
    result = build_remediator(model, settings=settings).run(
        raw_log_text=raw_log_text,
        repo=verify_repo,
        replay=False,
        job=None,
    )
    return result, active_run_id, raw_log_text
