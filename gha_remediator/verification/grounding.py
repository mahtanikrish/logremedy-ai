from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import os
import re
from typing import Any, Optional

from ..repo_context import preferred_node_manifest, preferred_node_workspace, primary_python_manifest
from ..types import RCAReport, RemediationPlan, RepoContext


_NPM_CI_RE = re.compile(r"^\s*npm\s+ci(?:\s|$)", re.IGNORECASE)
_NPM_RUN_RE = re.compile(r"^\s*npm\s+run\s+([A-Za-z0-9:_-]+)(?:\s|$)", re.IGNORECASE)
_PNPM_RUN_RE = re.compile(r"^\s*pnpm\s+run\s+([A-Za-z0-9:_-]+)(?:\s|$)", re.IGNORECASE)
_YARN_RUN_RE = re.compile(r"^\s*yarn\s+([A-Za-z0-9:_-]+)(?:\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class GroundingDecision:
    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    sandbox_workdir: str = "."


def evaluate_grounding(
    plan: RemediationPlan,
    *,
    repo: str,
    report: Optional[RCAReport] = None,
    repo_context: Optional[RepoContext] = None,
) -> GroundingDecision:
    repo_root = Path(repo).expanduser()
    command_decision = _evaluate_command_grounding(plan, repo_context=repo_context)
    if not command_decision.allowed:
        return command_decision

    patch_details: list[dict[str, Any]] = []
    strong_signals = 0

    for patch in plan.patches:
        decision = _evaluate_patch_grounding(
            patch.path,
            repo_root=repo_root,
            plan=plan,
            report=report,
            repo_context=repo_context,
        )
        patch_details.append(decision)
        if not decision["allowed"]:
            return GroundingDecision(
                False,
                f"ungrounded patch target: {patch.path}",
                {
                    "path": patch.path,
                    "patch_grounding": patch_details,
                    "command_grounding": command_decision.details,
                },
                sandbox_workdir=command_decision.sandbox_workdir,
            )
        if decision.get("strength") == "strong":
            strong_signals += 1

    if plan.patches and strong_signals == 0 and repo_context is not None and repo_context.candidate_files:
        return GroundingDecision(
            False,
            "patched files are not strongly grounded in repo context or failure evidence",
            {
                "patch_grounding": patch_details,
                "command_grounding": command_decision.details,
            },
            sandbox_workdir=command_decision.sandbox_workdir,
        )

    return GroundingDecision(
        True,
        "grounding checks passed",
        {
            "patch_grounding": patch_details,
            "command_grounding": command_decision.details,
        },
        sandbox_workdir=command_decision.sandbox_workdir,
    )


def _evaluate_patch_grounding(
    patch_path: str,
    *,
    repo_root: Path,
    plan: RemediationPlan,
    report: Optional[RCAReport],
    repo_context: Optional[RepoContext],
) -> dict[str, Any]:
    normalized = PurePosixPath(patch_path.replace("\\", "/").strip()).as_posix()
    full_path = repo_root / normalized
    exists = full_path.exists()

    candidate_paths = {candidate.path for candidate in (repo_context.candidate_files if repo_context else [])}
    candidate_dirs = {
        PurePosixPath(candidate.path).parent.as_posix()
        for candidate in (repo_context.candidate_files if repo_context else [])
    }
    manifests = set(repo_context.manifests if repo_context else [])
    lockfiles = set(repo_context.lockfiles if repo_context else [])
    workflow_files = set(repo_context.workflow_files if repo_context else [])
    preferred_python = primary_python_manifest(repo_context)
    preferred_node = preferred_node_manifest(repo_context)

    reasons: list[str] = []
    strength = "weak"

    if normalized in candidate_paths:
        reasons.append("exact candidate file from failure evidence")
        strength = "strong"
    promoted = _promote_unique_candidate_match(
        normalized,
        repo_root=repo_root,
        repo_context=repo_context,
    )
    if promoted is not None:
        reasons.append(
            f"unique repo match promoted from candidate {promoted['candidate_path']}"
        )
        strength = "strong"
    if normalized in manifests:
        reasons.append("known manifest file")
        strength = "strong"
    if normalized in lockfiles:
        reasons.append("known lockfile")
        strength = "strong"
    if normalized in workflow_files:
        reasons.append("known workflow file")
        strength = "strong"
    if normalized.startswith(".github/workflows/") and normalized.endswith((".yml", ".yaml")):
        reasons.append("workflow path")
        strength = "strong"
    if Path(normalized).name in {"requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml"}:
        reasons.append("supported manifest target")
        strength = "strong"
    if preferred_python and normalized == preferred_python:
        reasons.append("preferred python manifest")
        strength = "strong"
    if preferred_node and normalized == preferred_node:
        reasons.append("preferred node manifest")
        strength = "strong"
    if report is not None and _path_mentioned_in_report(normalized, report):
        reasons.append("path mentioned in RCA evidence")
        strength = "strong"

    parent = PurePosixPath(normalized).parent.as_posix()
    if strength != "strong" and parent in candidate_dirs and parent != ".":
        reasons.append("same directory as candidate evidence")
        strength = "weak"

    top_level = PurePosixPath(normalized).parts[0] if PurePosixPath(normalized).parts else ""
    candidate_top_levels = {
        PurePosixPath(candidate.path).parts[0]
        for candidate in (repo_context.candidate_files if repo_context else [])
        if PurePosixPath(candidate.path).parts
    }
    if strength != "strong" and top_level and top_level in candidate_top_levels:
        reasons.append("same top-level workspace as candidate evidence")

    if not reasons and exists:
        if repo_context is None:
            reasons.append("existing file in repository")
        elif not repo_context.candidate_files:
            reasons.append("existing file in repository (no candidate evidence available)")
        else:
            return {
                "allowed": False,
                "path": normalized,
                "exists": True,
                "strength": "none",
                "reason": "file exists but is unrelated to extracted candidate evidence",
            }

    if not exists:
        if normalized in candidate_paths:
            reasons.append("missing file explicitly referenced by failure evidence")
            strength = "strong"
        elif _supported_creation_target(normalized, repo_root, plan, repo_context):
            reasons.append("supported config or manifest creation target")
        else:
            return {
                "allowed": False,
                "path": normalized,
                "exists": False,
                "strength": "none",
                "reason": "new file target is not grounded in repo context",
            }

    if not reasons:
        return {
            "allowed": False,
            "path": normalized,
            "exists": exists,
            "strength": "none",
            "reason": "no grounding signals found for target file",
        }

    decision = {
        "allowed": True,
        "path": normalized,
        "exists": exists,
        "strength": strength,
        "reason": "; ".join(reasons),
    }
    if promoted is not None:
        decision["promotion"] = promoted
    return decision


def _supported_creation_target(
    normalized_path: str,
    repo_root: Path,
    plan: RemediationPlan,
    repo_context: Optional[RepoContext],
) -> bool:
    candidate = repo_root / normalized_path
    parent = candidate.parent
    if not parent.exists() or not parent.is_dir():
        return False

    basename = Path(normalized_path).name
    if basename in {"requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "pnpm-lock.yaml"}:
        return True

    if repo_context is not None:
        preferred_python = primary_python_manifest(repo_context)
        preferred_node = preferred_node_manifest(repo_context)
        preferred_node_workspace_path = preferred_node_workspace(repo_context)
        if preferred_python and parent == (repo_root / PurePosixPath(preferred_python).parent.as_posix()):
            return True
        if preferred_node and parent == (repo_root / PurePosixPath(preferred_node).parent.as_posix()):
            return True
        if preferred_node_workspace_path and parent == (repo_root / preferred_node_workspace_path):
            return True

    if plan.fix_type in {"workflow_yaml_fix_hint", "spelling_correction"}:
        return True

    return False


def _evaluate_command_grounding(
    plan: RemediationPlan,
    *,
    repo_context: Optional[RepoContext],
) -> GroundingDecision:
    sandbox_workdir = "."
    command_details: list[dict[str, Any]] = []

    preferred_node = preferred_node_manifest(repo_context)
    preferred_node_workspace_path = preferred_node_workspace(repo_context)
    preferred_python = primary_python_manifest(repo_context)

    for command in plan.commands:
        lowered = command.strip().lower()
        detail = {"command": command, "grounded": True, "reason": "command accepted"}

        if lowered.startswith(("npm ", "pnpm ", "yarn ")):
            if preferred_node is None:
                return GroundingDecision(
                    False,
                    "node command is ungrounded: no Node workspace was detected",
                    {"command_grounding": command_details + [{"command": command, "grounded": False}]},
                    sandbox_workdir=sandbox_workdir,
                )

            scripts = repo_context.package_scripts.get(preferred_node, {}) if repo_context else {}
            if lowered.startswith("npm "):
                match = _NPM_RUN_RE.match(command)
                if _NPM_CI_RE.match(command) and not _workspace_has_lockfile(repo_context, preferred_node_workspace_path, {"package-lock.json", "npm-shrinkwrap.json"}):
                    return GroundingDecision(
                        False,
                        "npm ci is ungrounded: no npm lockfile was detected for the selected workspace",
                        {"command_grounding": command_details + [{"command": command, "grounded": False}]},
                        sandbox_workdir=sandbox_workdir,
                    )
                if match and match.group(1) not in scripts:
                    return GroundingDecision(
                        False,
                        f"npm run {match.group(1)} is ungrounded: script was not found in {preferred_node}",
                        {"command_grounding": command_details + [{"command": command, "grounded": False}]},
                        sandbox_workdir=sandbox_workdir,
                    )
            elif lowered.startswith("pnpm "):
                match = _PNPM_RUN_RE.match(command)
                if repo_context and repo_context.package_managers.get(preferred_node) not in {None, "pnpm"}:
                    return GroundingDecision(
                        False,
                        "pnpm command is ungrounded: preferred workspace is configured for a different package manager",
                        {"command_grounding": command_details + [{"command": command, "grounded": False}]},
                        sandbox_workdir=sandbox_workdir,
                    )
                if match and match.group(1) not in scripts:
                    return GroundingDecision(
                        False,
                        f"pnpm run {match.group(1)} is ungrounded: script was not found in {preferred_node}",
                        {"command_grounding": command_details + [{"command": command, "grounded": False}]},
                        sandbox_workdir=sandbox_workdir,
                    )
            elif lowered.startswith("yarn "):
                match = _YARN_RUN_RE.match(command)
                if match and match.group(1) not in {"install", "add"} and match.group(1) not in scripts:
                    return GroundingDecision(
                        False,
                        f"yarn {match.group(1)} is ungrounded: script was not found in {preferred_node}",
                        {"command_grounding": command_details + [{"command": command, "grounded": False}]},
                        sandbox_workdir=sandbox_workdir,
                    )

            if preferred_node_workspace_path:
                sandbox_workdir = preferred_node_workspace_path
                detail["reason"] = f"node command grounded to workspace {preferred_node_workspace_path}"
                detail["workdir"] = preferred_node_workspace_path

        elif lowered.startswith(("python ", "pytest ", "pip ")):
            if preferred_python:
                sandbox_workdir = PurePosixPath(preferred_python).parent.as_posix()
                detail["reason"] = f"python command grounded to workspace {sandbox_workdir}"
                detail["workdir"] = sandbox_workdir

        command_details.append(detail)

    return GroundingDecision(
        True,
        "command grounding checks passed",
        {"commands": command_details},
        sandbox_workdir=sandbox_workdir,
    )


def _workspace_has_lockfile(
    repo_context: Optional[RepoContext],
    workspace: Optional[str],
    names: set[str],
) -> bool:
    if repo_context is None or workspace is None:
        return False
    expected_parent = "." if workspace == "." else workspace
    for path in repo_context.lockfiles:
        parent = PurePosixPath(path).parent.as_posix()
        parent = "." if parent == "." else parent
        if parent == expected_parent and Path(path).name in names:
            return True
    return False


def _path_mentioned_in_report(path: str, report: RCAReport) -> bool:
    if not path:
        return False
    basename = Path(path).name.lower()
    haystacks = [
        report.root_cause_label or "",
        report.root_cause_text or "",
        *report.root_causes,
        *(line.text for line in report.key_lines[:200]),
    ]
    lowered_path = path.lower()
    for text in haystacks:
        lowered = text.lower()
        if lowered_path in lowered or basename in lowered:
            return True
    return False


def _promote_unique_candidate_match(
    patch_path: str,
    *,
    repo_root: Path,
    repo_context: Optional[RepoContext],
) -> Optional[dict[str, Any]]:
    if repo_context is None:
        return None

    matches: list[dict[str, Any]] = []
    seen_candidates: set[str] = set()
    for candidate in repo_context.candidate_files:
        candidate_path = PurePosixPath(candidate.path).as_posix().lstrip("./")
        if not candidate_path or candidate_path in seen_candidates:
            continue
        seen_candidates.add(candidate_path)
        if candidate_path == patch_path:
            continue
        if not _candidate_can_ground_patch(candidate_path, patch_path):
            continue
        resolved = _unique_repo_suffix_match(repo_root, candidate_path)
        if resolved is None or resolved != patch_path:
            continue
        matches.append(
            {
                "candidate_path": candidate_path,
                "resolved_path": resolved,
                "candidate_reason": candidate.reason,
            }
        )

    if not matches:
        return None

    resolved_paths = {item["resolved_path"] for item in matches}
    if len(resolved_paths) != 1:
        return None
    return matches[0]


def _candidate_can_ground_patch(candidate_path: str, patch_path: str) -> bool:
    if candidate_path == patch_path:
        return True
    if patch_path.endswith(f"/{candidate_path}"):
        return True
    return Path(candidate_path).name == Path(patch_path).name


def _unique_repo_suffix_match(repo_root: Path, suffix_path: str) -> Optional[str]:
    suffix = PurePosixPath(suffix_path).as_posix().lstrip("./")
    basename = Path(suffix).name
    if not basename:
        return None

    matches: list[str] = []
    for full_path in repo_root.rglob(basename):
        if not full_path.is_file():
            continue
        relative = full_path.relative_to(repo_root).as_posix()
        if relative == suffix or relative.endswith(f"/{suffix}"):
            matches.append(relative)
            if len(matches) > 1:
                return None
    return matches[0] if matches else None
