from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from statistics import median
import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ..verification.policy import is_patch_allowed


PARQUET_RELATIVE_PATHS = {
    "default": Path("data/python/test-00000-of-00001.parquet"),
    "old": Path("old/python/test-00000-of-00001.parquet"),
}

KNOWN_MANIFEST_FILES = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "poetry.lock",
    "setup.py",
    "setup.cfg",
    "tox.ini",
    "Pipfile",
    "Pipfile.lock",
    "environment.yml",
    "environment.yaml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
}


@dataclass(frozen=True)
class AuditCase:
    config: str
    case_id: int
    repo: str
    workflow_path: str
    sha_fail: str
    sha_success: str
    difficulty: int
    changed_files_count: int
    changed_files: List[str]
    disallowed_paths_now: List[str]
    all_changed_files_allowed_now: bool
    any_changed_files_allowed_now: bool
    touches_workflow_file: bool
    static_checks_applicable_now: bool
    change_surface: str
    log_step_count: int
    log_line_count: int
    workflow_line_count: int
    diff_hunk_count: int
    diff_additions: int
    diff_deletions: int
    ubuntu_only: bool
    includes_windows: bool
    includes_macos: bool
    uses_self_hosted: bool
    uses_services: bool
    uses_matrix: bool
    uses_container: bool
    uses_secrets: bool
    context_eval_ready: bool
    verification_eval_possible_in_principle: bool
    verification_readiness_now: str
    local_replay_risk: str
    component_priority_score: float
    verification_priority_score: float
    notes: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_pyarrow_parquet():
    try:
        import pyarrow.parquet as pq  # type: ignore
    except Exception as exc:  # pragma: no cover - import path depends on local env
        raise RuntimeError(
            "pyarrow is required for LCA dataset auditing. "
            "Install it with `pip install pyarrow`."
        ) from exc
    return pq


def resolve_dataset_root(candidate: str | None = None) -> Path:
    if candidate:
        root = Path(candidate).expanduser().resolve()
        if root.exists():
            return root
        raise FileNotFoundError(f"LCA dataset root not found: {root}")

    search_roots = [
        Path.cwd() / "lca-ci-builds-repair-dataset",
        Path.cwd().parent / "lca-ci-builds-repair-dataset",
        Path.home() / "Desktop/UCL/lca-ci-builds-repair-dataset",
    ]
    for root in search_roots:
        if root.exists():
            return root.resolve()
    raise FileNotFoundError(
        "Could not find the LCA dataset root automatically. "
        "Pass --dataset-root explicitly."
    )


def dataset_parquet_path(dataset_root: str | Path, config: str) -> Path:
    try:
        relative = PARQUET_RELATIVE_PATHS[config]
    except KeyError as exc:
        expected = ", ".join(sorted(PARQUET_RELATIVE_PATHS))
        raise ValueError(f"Unsupported config '{config}'. Expected one of: {expected}") from exc
    return Path(dataset_root).expanduser().resolve() / relative


def load_dataset_rows(dataset_root: str | Path, config: str) -> List[Dict[str, Any]]:
    parquet_path = dataset_parquet_path(dataset_root, config)
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")
    pq = _load_pyarrow_parquet()
    table = pq.read_table(parquet_path)
    columns = {name: table.column(name).to_pylist() for name in table.schema.names}
    rows: List[Dict[str, Any]] = []
    for idx in range(table.num_rows):
        rows.append({name: values[idx] for name, values in columns.items()})
    return rows


def _normalize_logs(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: List[Dict[str, str]] = []
    for item in value:
        if isinstance(item, Mapping):
            step_name = str(item.get("step_name", ""))
            log_text = str(item.get("log", ""))
            normalized.append({"step_name": step_name, "log": log_text})
        elif isinstance(item, str):
            normalized.append({"step_name": "", "log": item})
    return normalized


def _normalize_changed_files(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value in (None, ""):
        return []
    return [str(value)]


def _runner_profile(workflow_text: str) -> Dict[str, bool]:
    lower = workflow_text.lower()
    includes_windows = "windows-latest" in lower or re.search(r"runs-on:\s*windows", lower) is not None
    includes_macos = "macos-latest" in lower or re.search(r"runs-on:\s*macos", lower) is not None
    uses_self_hosted = "self-hosted" in lower
    uses_services = re.search(r"(?m)^\s*services\s*:", workflow_text) is not None
    uses_matrix = re.search(r"(?m)^\s*matrix\s*:", workflow_text) is not None
    uses_container = re.search(r"(?m)^\s*container\s*:", workflow_text) is not None
    uses_secrets = "${{ secrets" in lower or "secrets." in lower
    ubuntu_only = (
        ("ubuntu-latest" in lower or re.search(r"runs-on:\s*ubuntu", lower) is not None)
        and not includes_windows
        and not includes_macos
        and not uses_self_hosted
    )
    return {
        "ubuntu_only": ubuntu_only,
        "includes_windows": includes_windows,
        "includes_macos": includes_macos,
        "uses_self_hosted": uses_self_hosted,
        "uses_services": uses_services,
        "uses_matrix": uses_matrix,
        "uses_container": uses_container,
        "uses_secrets": uses_secrets,
    }


def _path_surface(path: str) -> str:
    if path.startswith(".github/workflows/"):
        return "workflow"
    if path.startswith(".github/"):
        return "github_meta"
    name = Path(path).name
    suffix = Path(path).suffix.lower()
    lower = path.lower()
    if name in KNOWN_MANIFEST_FILES:
        return "manifest"
    if (
        lower.startswith("tests/")
        or lower.startswith("test/")
        or "/tests/" in lower
        or "/test/" in lower
    ):
        return "test"
    if lower.startswith("docs/") or suffix in {".md", ".rst"}:
        return "docs"
    if suffix in {".yml", ".yaml", ".json", ".ini", ".cfg", ".toml"}:
        return "config"
    return "source"


def _summarize_change_surface(paths: Sequence[str]) -> str:
    if not paths:
        return "unknown"
    surfaces = {_path_surface(path) for path in paths}
    if surfaces <= {"workflow"}:
        return "workflow_only"
    if surfaces <= {"workflow", "github_meta", "manifest", "config", "docs"}:
        return "config_or_docs_only"
    if "source" in surfaces and surfaces <= {"source"}:
        return "source_only"
    if "source" in surfaces or "test" in surfaces:
        return "code_touching"
    return "mixed_meta"


def _diff_stats(diff_text: str) -> Dict[str, int]:
    additions = 0
    deletions = 0
    hunks = 0
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            hunks += 1
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {"diff_hunk_count": hunks, "diff_additions": additions, "diff_deletions": deletions}


def _component_priority_score(
    *,
    difficulty: int,
    changed_files_count: int,
    log_step_count: int,
    log_line_count: int,
    workflow_line_count: int,
) -> float:
    score = 100.0
    score -= difficulty * 15.0
    score -= max(0, changed_files_count - 1) * 8.0
    score -= max(0, log_step_count - 1) * 4.0
    score -= min(log_line_count, 5000) / 120.0
    score -= min(workflow_line_count, 400) / 80.0
    return round(max(score, 0.0), 2)


def _verification_priority_score(
    *,
    component_score: float,
    all_changed_files_allowed_now: bool,
    ubuntu_only: bool,
    includes_windows: bool,
    includes_macos: bool,
    uses_self_hosted: bool,
    uses_services: bool,
    uses_matrix: bool,
    uses_container: bool,
    uses_secrets: bool,
) -> float:
    score = component_score
    if not all_changed_files_allowed_now:
        score -= 30.0
    if not ubuntu_only:
        score -= 10.0
    if includes_windows:
        score -= 8.0
    if includes_macos:
        score -= 8.0
    if uses_self_hosted:
        score -= 20.0
    if uses_services:
        score -= 15.0
    if uses_matrix:
        score -= 5.0
    if uses_container:
        score -= 5.0
    if uses_secrets:
        score -= 8.0
    return round(max(score, 0.0), 2)


def _local_replay_risk(
    *,
    ubuntu_only: bool,
    includes_windows: bool,
    includes_macos: bool,
    uses_self_hosted: bool,
    uses_services: bool,
    uses_container: bool,
    uses_secrets: bool,
    log_step_count: int,
    changed_files_count: int,
) -> str:
    if includes_windows or includes_macos or uses_self_hosted:
        return "high"
    if not ubuntu_only or uses_container or uses_secrets or uses_services:
        return "medium"
    if log_step_count <= 2 and changed_files_count <= 2:
        return "low"
    return "medium"


def audit_case(row: Mapping[str, Any], *, config: str) -> AuditCase:
    logs = _normalize_logs(row.get("logs"))
    changed_files = _normalize_changed_files(row.get("changed_files"))
    workflow_text = str(row.get("workflow", ""))
    log_line_count = sum(len(entry.get("log", "").splitlines()) for entry in logs)
    workflow_line_count = len(workflow_text.splitlines())
    diff_text = str(row.get("diff", ""))
    diff_stats = _diff_stats(diff_text)

    policy_checks = {path: is_patch_allowed(path) for path in changed_files}
    disallowed_now = [path for path, decision in policy_checks.items() if not decision.allowed]
    all_allowed_now = bool(changed_files) and not disallowed_now
    any_allowed_now = any(decision.allowed for decision in policy_checks.values())

    runner_profile = _runner_profile(workflow_text)
    touches_workflow_file = any(path.startswith(".github/workflows/") for path in changed_files)
    component_score = _component_priority_score(
        difficulty=int(row.get("difficulty", 0) or 0),
        changed_files_count=len(changed_files),
        log_step_count=len(logs),
        log_line_count=log_line_count,
        workflow_line_count=workflow_line_count,
    )
    verification_score = _verification_priority_score(
        component_score=component_score,
        all_changed_files_allowed_now=all_allowed_now,
        ubuntu_only=runner_profile["ubuntu_only"],
        includes_windows=runner_profile["includes_windows"],
        includes_macos=runner_profile["includes_macos"],
        uses_self_hosted=runner_profile["uses_self_hosted"],
        uses_services=runner_profile["uses_services"],
        uses_matrix=runner_profile["uses_matrix"],
        uses_container=runner_profile["uses_container"],
        uses_secrets=runner_profile["uses_secrets"],
    )
    replay_risk = _local_replay_risk(
        ubuntu_only=runner_profile["ubuntu_only"],
        includes_windows=runner_profile["includes_windows"],
        includes_macos=runner_profile["includes_macos"],
        uses_self_hosted=runner_profile["uses_self_hosted"],
        uses_services=runner_profile["uses_services"],
        uses_container=runner_profile["uses_container"],
        uses_secrets=runner_profile["uses_secrets"],
        log_step_count=len(logs),
        changed_files_count=len(changed_files),
    )

    notes: List[str] = []
    if not all_allowed_now:
        notes.append("gold diff is blocked by current patch policy")
    if runner_profile["uses_services"]:
        notes.append("workflow uses GitHub Actions services")
    if runner_profile["uses_self_hosted"]:
        notes.append("workflow uses self-hosted runners")
    if runner_profile["includes_windows"] or runner_profile["includes_macos"]:
        notes.append("workflow is not ubuntu-only")
    if runner_profile["uses_secrets"]:
        notes.append("workflow references secrets")

    verification_readiness_now = "blocked_by_policy"
    if all_allowed_now and replay_risk == "low":
        verification_readiness_now = "candidate_now"
    elif all_allowed_now:
        verification_readiness_now = "candidate_with_replay_risk"
    elif replay_risk == "high":
        verification_readiness_now = "blocked_by_policy_and_high_replay_risk"

    return AuditCase(
        config=config,
        case_id=int(row.get("id", 0) or 0),
        repo=f"{row.get('repo_owner', '')}/{row.get('repo_name', '')}",
        workflow_path=str(row.get("workflow_path", "")),
        sha_fail=str(row.get("sha_fail", "")),
        sha_success=str(row.get("sha_success", "")),
        difficulty=int(row.get("difficulty", 0) or 0),
        changed_files_count=len(changed_files),
        changed_files=changed_files,
        disallowed_paths_now=disallowed_now,
        all_changed_files_allowed_now=all_allowed_now,
        any_changed_files_allowed_now=any_allowed_now,
        touches_workflow_file=touches_workflow_file,
        static_checks_applicable_now=touches_workflow_file,
        change_surface=_summarize_change_surface(changed_files),
        log_step_count=len(logs),
        log_line_count=log_line_count,
        workflow_line_count=workflow_line_count,
        diff_hunk_count=diff_stats["diff_hunk_count"],
        diff_additions=diff_stats["diff_additions"],
        diff_deletions=diff_stats["diff_deletions"],
        ubuntu_only=runner_profile["ubuntu_only"],
        includes_windows=runner_profile["includes_windows"],
        includes_macos=runner_profile["includes_macos"],
        uses_self_hosted=runner_profile["uses_self_hosted"],
        uses_services=runner_profile["uses_services"],
        uses_matrix=runner_profile["uses_matrix"],
        uses_container=runner_profile["uses_container"],
        uses_secrets=runner_profile["uses_secrets"],
        context_eval_ready=bool(logs and workflow_text),
        verification_eval_possible_in_principle=bool(
            changed_files
            and row.get("sha_fail")
            and row.get("sha_success")
            and diff_text
            and row.get("repo_owner")
            and row.get("repo_name")
        ),
        verification_readiness_now=verification_readiness_now,
        local_replay_risk=replay_risk,
        component_priority_score=component_score,
        verification_priority_score=verification_score,
        notes=notes,
    )


def audit_cases(rows: Iterable[Mapping[str, Any]], *, config: str) -> List[AuditCase]:
    return [audit_case(row, config=config) for row in rows]


def _median_int(values: Sequence[int]) -> float:
    if not values:
        return 0.0
    return float(median(values))


def _top_cases(
    cases: Sequence[AuditCase],
    *,
    sort_key: str,
    limit: int,
    predicate: Any = None,
) -> List[Dict[str, Any]]:
    selected = list(cases)
    if predicate is not None:
        selected = [case for case in selected if predicate(case)]
    selected.sort(
        key=lambda case: (
            -getattr(case, sort_key),
            case.difficulty,
            case.changed_files_count,
            case.log_line_count,
            case.case_id,
        )
    )
    return [
        {
            "case_id": case.case_id,
            "repo": case.repo,
            "difficulty": case.difficulty,
            "workflow_path": case.workflow_path,
            "changed_files_count": case.changed_files_count,
            "changed_files": case.changed_files,
            "component_priority_score": case.component_priority_score,
            "verification_priority_score": case.verification_priority_score,
            "verification_readiness_now": case.verification_readiness_now,
            "local_replay_risk": case.local_replay_risk,
            "notes": case.notes,
        }
        for case in selected[:limit]
    ]


def summarize_audit_cases(cases: Sequence[AuditCase], *, top_n: int = 15) -> Dict[str, Any]:
    difficulty_counts = Counter(case.difficulty for case in cases)
    change_surface_counts = Counter(case.change_surface for case in cases)
    readiness_counts = Counter(case.verification_readiness_now for case in cases)
    replay_risk_counts = Counter(case.local_replay_risk for case in cases)

    changed_files = [case.changed_files_count for case in cases]
    log_steps = [case.log_step_count for case in cases]
    log_lines = [case.log_line_count for case in cases]
    workflow_lines = [case.workflow_line_count for case in cases]

    summary = {
        "rows": len(cases),
        "unique_repos": len({case.repo for case in cases}),
        "difficulty_counts": dict(sorted(difficulty_counts.items())),
        "change_surface_counts": dict(sorted(change_surface_counts.items())),
        "verification_readiness_counts": dict(sorted(readiness_counts.items())),
        "local_replay_risk_counts": dict(sorted(replay_risk_counts.items())),
        "all_changed_files_allowed_now": sum(1 for case in cases if case.all_changed_files_allowed_now),
        "any_changed_files_allowed_now": sum(1 for case in cases if case.any_changed_files_allowed_now),
        "static_checks_applicable_now": sum(1 for case in cases if case.static_checks_applicable_now),
        "context_eval_ready": sum(1 for case in cases if case.context_eval_ready),
        "verification_eval_possible_in_principle": sum(
            1 for case in cases if case.verification_eval_possible_in_principle
        ),
        "ubuntu_only": sum(1 for case in cases if case.ubuntu_only),
        "uses_services": sum(1 for case in cases if case.uses_services),
        "uses_self_hosted": sum(1 for case in cases if case.uses_self_hosted),
        "uses_matrix": sum(1 for case in cases if case.uses_matrix),
        "uses_container": sum(1 for case in cases if case.uses_container),
        "uses_secrets": sum(1 for case in cases if case.uses_secrets),
        "includes_windows": sum(1 for case in cases if case.includes_windows),
        "includes_macos": sum(1 for case in cases if case.includes_macos),
        "stats": {
            "changed_files_mean": round(sum(changed_files) / len(changed_files), 2) if changed_files else 0.0,
            "changed_files_median": _median_int(changed_files),
            "log_steps_mean": round(sum(log_steps) / len(log_steps), 2) if log_steps else 0.0,
            "log_steps_median": _median_int(log_steps),
            "log_lines_mean": round(sum(log_lines) / len(log_lines), 2) if log_lines else 0.0,
            "log_lines_median": _median_int(log_lines),
            "workflow_lines_mean": round(sum(workflow_lines) / len(workflow_lines), 2)
            if workflow_lines
            else 0.0,
            "workflow_lines_median": _median_int(workflow_lines),
        },
        "top_component_candidates": _top_cases(
            cases,
            sort_key="component_priority_score",
            limit=top_n,
        ),
        "top_verification_candidates": _top_cases(
            cases,
            sort_key="verification_priority_score",
            limit=top_n,
        ),
        "top_low_replay_risk_candidates": _top_cases(
            cases,
            sort_key="verification_priority_score",
            limit=top_n,
            predicate=lambda case: case.local_replay_risk == "low",
        ),
        "top_meta_change_candidates": _top_cases(
            cases,
            sort_key="verification_priority_score",
            limit=top_n,
            predicate=lambda case: case.change_surface == "config_or_docs_only",
        ),
    }
    return summary


def audit_dataset(dataset_root: str | Path, *, config: str, top_n: int = 15) -> Dict[str, Any]:
    rows = load_dataset_rows(dataset_root, config)
    audited = audit_cases(rows, config=config)
    return {
        "config": config,
        "dataset_root": str(Path(dataset_root).expanduser().resolve()),
        "parquet_path": str(dataset_parquet_path(dataset_root, config)),
        "summary": summarize_audit_cases(audited, top_n=top_n),
        "cases": [case.to_dict() for case in audited],
    }


def write_audit_outputs(audit_report: Mapping[str, Any], *, out_dir: str | Path) -> Dict[str, str]:
    config = str(audit_report["config"])
    root = Path(out_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    summary_path = root / f"{config}_summary.json"
    cases_path = root / f"{config}_cases.jsonl"
    shortlists_path = root / f"{config}_shortlists.json"

    summary_payload = {
        "config": audit_report["config"],
        "dataset_root": audit_report["dataset_root"],
        "parquet_path": audit_report["parquet_path"],
        "summary": audit_report["summary"],
    }
    summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    case_lines = [json.dumps(case, sort_keys=True) for case in audit_report["cases"]]
    cases_path.write_text("\n".join(case_lines) + ("\n" if case_lines else ""), encoding="utf-8")

    shortlist_payload = {
        "config": audit_report["config"],
        "top_component_candidates": audit_report["summary"]["top_component_candidates"],
        "top_verification_candidates": audit_report["summary"]["top_verification_candidates"],
        "top_low_replay_risk_candidates": audit_report["summary"]["top_low_replay_risk_candidates"],
        "top_meta_change_candidates": audit_report["summary"]["top_meta_change_candidates"],
    }
    shortlists_path.write_text(json.dumps(shortlist_payload, indent=2), encoding="utf-8")

    return {
        "summary_path": str(summary_path),
        "cases_path": str(cases_path),
        "shortlists_path": str(shortlists_path),
    }
