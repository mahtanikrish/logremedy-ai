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


def _normalize_relpath(raw_path: str) -> str:
    normalized = raw_path.strip().replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _strip_diff_prefix(path: str) -> str:
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _paths_compatible(left: str, right: str) -> bool:
    if left == right:
        return True
    return left.endswith(f"/{right}") or right.endswith(f"/{left}")


def _looks_like_git_diff(diff_text: str) -> bool:
    return (
        "diff --git a/" in diff_text
        or "\n--- a/" in diff_text
        or diff_text.startswith("--- a/")
    )


def _split_diff_header(line: str) -> tuple[str, str, str] | None:
    if line.startswith("--- "):
        prefix = "--- "
    elif line.startswith("+++ "):
        prefix = "+++ "
    else:
        return None
    payload = line[len(prefix):]
    if not payload:
        return None
    path, sep, suffix = payload.partition("\t")
    return prefix, path.strip(), f"{sep}{suffix}" if sep else ""


def _canonicalize_patch(patch_path: str, diff_text: str) -> tuple[str, dict[str, Any]]:
    canonical_path = _normalize_relpath(patch_path)
    lines = diff_text.splitlines(keepends=True)
    changed_headers: list[dict[str, str]] = []
    changed_git_headers: list[dict[str, str]] = []
    out: list[str] = []

    for line in lines:
        header = _split_diff_header(line)
        if header is not None:
            prefix, raw_path, suffix = header
            if raw_path != "/dev/null":
                normalized_header = _normalize_relpath(_strip_diff_prefix(raw_path))
                if _paths_compatible(normalized_header, canonical_path):
                    replacement = canonical_path
                    if replacement != raw_path:
                        changed_headers.append(
                            {
                                "prefix": prefix.strip(),
                                "before": raw_path,
                                "after": replacement,
                            }
                        )
                        line = f"{prefix}{replacement}{suffix}"
                        if not line.endswith("\n"):
                            line += "\n"
            out.append(line)
            continue

        if line.startswith("diff --git "):
            parts = line.rstrip("\n").split()
            if len(parts) >= 4:
                left = _normalize_relpath(_strip_diff_prefix(parts[2]))
                right = _normalize_relpath(_strip_diff_prefix(parts[3]))
                if _paths_compatible(left, canonical_path) and _paths_compatible(right, canonical_path):
                    before = f"{parts[2]} {parts[3]}"
                    parts[2] = f"a/{canonical_path}"
                    parts[3] = f"b/{canonical_path}"
                    after = f"{parts[2]} {parts[3]}"
                    if before != after:
                        changed_git_headers.append({"before": before, "after": after})
                        line = " ".join(parts) + "\n"
            out.append(line)
            continue

        out.append(line)

    payload = "".join(out)
    if payload and not payload.endswith("\n"):
        payload += "\n"

    return payload, {
        "original_path": patch_path,
        "canonical_path": canonical_path,
        "header_rewrites": changed_headers,
        "git_header_rewrites": changed_git_headers,
        "diff_rewritten": bool(changed_headers or changed_git_headers or patch_path != canonical_path),
    }


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
    touched_paths = []
    if not plan.patches:
        return {
            "status": "skipped",
            "reason": "no patches to apply",
            "details": {"paths": []},
        }

    repo_path = Path(workspace.patched_repo)
    canonicalization: list[dict[str, Any]] = []
    for index, patch in enumerate(plan.patches):
        try:
            canonical_diff, patch_canonicalization = _canonicalize_patch(patch.path, patch.diff)
            canonicalization.append(patch_canonicalization)
            touched_paths.append(patch_canonicalization["canonical_path"])
            checked, checked_strip_level = _run_git_apply(repo_path, canonical_diff, check=True)
            if checked.returncode != 0:
                raise WorkspacePreparationError(
                    gate="patch_apply",
                    reason=f"patch does not apply cleanly: {patch.path}",
                    details={
                        "path": patch.path,
                        "canonical_path": patch_canonicalization["canonical_path"],
                        "patch_index": index,
                        "mode": "check",
                        "strip_level": checked_strip_level,
                        "canonicalization": patch_canonicalization,
                        "stdout_tail": _tail(checked.stdout),
                        "stderr_tail": _tail(checked.stderr),
                    },
                )

            applied, applied_strip_level = _run_git_apply(repo_path, canonical_diff, check=False)
            if applied.returncode != 0:
                raise WorkspacePreparationError(
                    gate="patch_apply",
                    reason=f"failed to apply patch: {patch.path}",
                    details={
                        "path": patch.path,
                        "canonical_path": patch_canonicalization["canonical_path"],
                        "patch_index": index,
                        "mode": "apply",
                        "strip_level": applied_strip_level,
                        "canonicalization": patch_canonicalization,
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
        "details": {"paths": touched_paths, "canonicalization": canonicalization},
    }


def prepare_patched_workspace(repo: str, plan: RemediationPlan) -> PreparedWorkspace:
    workspace = prepare_workspace_copy(repo)
    try:
        apply_plan_patches(workspace, plan)
        return workspace
    except Exception:
        workspace.cleanup()
        raise
