from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict

from ..types import RemediationPlan


class WorkspacePreparationError(RuntimeError):
    def __init__(self, gate: str, reason: str, details: Dict[str, Any] | None = None):
        super().__init__(reason)
        self.gate = gate
        self.reason = reason
        self.details = details or {}


class PreparedWorkspace:
    def __init__(self, tmpdir: tempfile.TemporaryDirectory[str], patched_repo: Path):
        self._tmpdir = tmpdir
        self._patched_repo = patched_repo
        self._clone_index = 0

    @property
    def patched_repo(self) -> str:
        return str(self._patched_repo)

    def clone_for_gate(self, gate_name: str) -> str:
        safe_gate = re.sub(r"[^A-Za-z0-9_.-]+", "-", gate_name).strip("-") or "gate"
        target = Path(self._tmpdir.name) / f"{safe_gate}-{self._clone_index}"
        self._clone_index += 1
        shutil.copytree(self._patched_repo, target, symlinks=True)
        return str(target)

    def cleanup(self) -> None:
        self._tmpdir.cleanup()

    def __enter__(self) -> "PreparedWorkspace":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.cleanup()


def _tail(text: str, limit: int = 2000) -> str:
    return text[-limit:]


def _looks_like_git_diff(diff_text: str) -> bool:
    return (
        "diff --git a/" in diff_text
        or "\n--- a/" in diff_text
        or diff_text.startswith("--- a/")
    )


def _run_git_apply_once(
    repo_path: Path,
    diff_text: str,
    *,
    check: bool,
    strip_level: int,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git", "apply", f"-p{strip_level}"]
    if check:
        cmd.append("--check")
    cmd.append("-")
    payload = diff_text if diff_text.endswith("\n") else f"{diff_text}\n"
    return subprocess.run(
        cmd,
        cwd=repo_path,
        input=payload,
        capture_output=True,
        text=True,
    )


def _run_git_apply(
    repo_path: Path,
    diff_text: str,
    *,
    check: bool,
) -> tuple[subprocess.CompletedProcess[str], int]:
    strip_levels = [0]
    if _looks_like_git_diff(diff_text):
        strip_levels.append(1)

    last_result: subprocess.CompletedProcess[str] | None = None
    last_strip_level = 0
    for strip_level in strip_levels:
        result = _run_git_apply_once(
            repo_path,
            diff_text,
            check=check,
            strip_level=strip_level,
        )
        last_result = result
        last_strip_level = strip_level
        if result.returncode == 0:
            return result, strip_level

    assert last_result is not None
    return last_result, last_strip_level


def prepare_workspace_copy(repo: str) -> PreparedWorkspace:
    repo_path = Path(repo).expanduser()
    if not repo_path.exists() or not repo_path.is_dir():
        raise WorkspacePreparationError(
            gate="preconditions",
            reason=f"repo does not exist: {repo}",
            details={"repo": str(repo_path), "repo_exists": False},
        )

    tmpdir = tempfile.TemporaryDirectory(prefix="gha_verify_")
    patched_repo = Path(tmpdir.name) / "patched"
    try:
        shutil.copytree(repo_path, patched_repo, symlinks=True)
        return PreparedWorkspace(tmpdir, patched_repo)
    except Exception as exc:
        tmpdir.cleanup()
        raise WorkspacePreparationError(
            gate="preconditions",
            reason=f"failed to create verification workspace: {exc}",
            details={"repo": str(repo_path)},
        ) from exc


def apply_plan_patches(workspace: PreparedWorkspace, plan: RemediationPlan) -> Dict[str, Any]:
    touched_paths = [patch.path for patch in plan.patches]
    if not plan.patches:
        return {
            "status": "skipped",
            "reason": "no patches to apply",
            "details": {"paths": []},
        }

    repo_path = Path(workspace.patched_repo)
    for index, patch in enumerate(plan.patches):
        try:
            checked, checked_strip_level = _run_git_apply(repo_path, patch.diff, check=True)
            if checked.returncode != 0:
                raise WorkspacePreparationError(
                    gate="patch_apply",
                    reason=f"patch does not apply cleanly: {patch.path}",
                    details={
                        "path": patch.path,
                        "patch_index": index,
                        "mode": "check",
                        "strip_level": checked_strip_level,
                        "stdout_tail": _tail(checked.stdout),
                        "stderr_tail": _tail(checked.stderr),
                    },
                )

            applied, applied_strip_level = _run_git_apply(repo_path, patch.diff, check=False)
            if applied.returncode != 0:
                raise WorkspacePreparationError(
                    gate="patch_apply",
                    reason=f"failed to apply patch: {patch.path}",
                    details={
                        "path": patch.path,
                        "patch_index": index,
                        "mode": "apply",
                        "strip_level": applied_strip_level,
                        "stdout_tail": _tail(applied.stdout),
                        "stderr_tail": _tail(applied.stderr),
                    },
                )
        except FileNotFoundError as exc:
            raise WorkspacePreparationError(
                gate="patch_apply",
                reason="git is required to validate and apply patches",
                details={"path": patch.path, "patch_index": index},
            ) from exc

    return {
        "status": "passed",
        "reason": f"applied {len(plan.patches)} patch(es)",
        "details": {"paths": touched_paths},
    }


def prepare_patched_workspace(repo: str, plan: RemediationPlan) -> PreparedWorkspace:
    workspace = prepare_workspace_copy(repo)
    try:
        apply_plan_patches(workspace, plan)
        return workspace
    except Exception:
        workspace.cleanup()
        raise
