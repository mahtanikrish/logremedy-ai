from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Optional, Sequence

from ..types import Patch


VerificationProfile = Literal["strict", "benchmark_supported_files"]

ALLOWED_PATH_PREFIXES = (
    ".github/workflows/",
)
ALLOWED_FILES = {
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "tsconfig.json",
}

SUPPORTED_BENCHMARK_SUFFIXES = {
    ".md",
    ".py",
    ".json",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
    ".cfg",
    ".ini",
}

DISALLOWED_PATH_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "coverage",
}

BANNED_COMMAND_SUBSTRINGS = [
    "curl ",
    "wget ",
    "git ",
    "gh ",
    "svn ",
    "hg ",
    "rm -rf /",
    "sudo rm",
    "printenv",
    "cat $GITHUB_TOKEN",
]


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyConfig:
    profile: VerificationProfile
    max_patches: Optional[int]
    max_total_changed_lines: Optional[int]


STRICT_CONFIG = PolicyConfig(
    profile="strict",
    max_patches=None,
    max_total_changed_lines=None,
)

BENCHMARK_SUPPORTED_FILES_CONFIG = PolicyConfig(
    profile="benchmark_supported_files",
    max_patches=3,
    max_total_changed_lines=160,
)


def _config_for(profile: VerificationProfile) -> PolicyConfig:
    if profile == "strict":
        return STRICT_CONFIG
    if profile == "benchmark_supported_files":
        return BENCHMARK_SUPPORTED_FILES_CONFIG
    raise ValueError(f"Unsupported verification profile: {profile}")


def _normalize_repo_path(path: str) -> PurePosixPath:
    normalized = path.replace("\\", "/").strip()
    return PurePosixPath(normalized)


def _path_is_unsafe(path: str) -> Optional[str]:
    normalized = _normalize_repo_path(path)
    if not path.strip():
        return "empty patch path"
    if normalized.is_absolute():
        return f"absolute paths are not allowed: {path}"
    if any(part == ".." for part in normalized.parts):
        return f"path traversal is not allowed: {path}"
    if any(part in DISALLOWED_PATH_PARTS for part in normalized.parts):
        return f"path is inside a disallowed directory: {path}"
    return None


def patch_changed_line_count(diff: str) -> int:
    changed = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+") or line.startswith("-"):
            changed += 1
    return changed


def evaluate_patch_budget(
    patches: Sequence[Patch],
    *,
    profile: VerificationProfile = "strict",
) -> PolicyDecision:
    cfg = _config_for(profile)
    if cfg.max_patches is not None and len(patches) > cfg.max_patches:
        return PolicyDecision(
            False,
            f"too many patched files for {profile}: {len(patches)} > {cfg.max_patches}",
            {"profile": profile, "max_patches": cfg.max_patches, "patches": len(patches)},
        )

    if cfg.max_total_changed_lines is not None:
        total_changed_lines = sum(patch_changed_line_count(patch.diff) for patch in patches)
        if total_changed_lines > cfg.max_total_changed_lines:
            return PolicyDecision(
                False,
                (
                    f"patch diff too large for {profile}: "
                    f"{total_changed_lines} > {cfg.max_total_changed_lines} changed lines"
                ),
                {
                    "profile": profile,
                    "max_total_changed_lines": cfg.max_total_changed_lines,
                    "total_changed_lines": total_changed_lines,
                },
            )

    return PolicyDecision(True, "patch budget ok", {"profile": profile})


def evaluate_patch_policy(
    path: str,
    *,
    repo: Optional[str] = None,
    profile: VerificationProfile = "strict",
) -> PolicyDecision:
    unsafe_reason = _path_is_unsafe(path)
    if unsafe_reason is not None:
        return PolicyDecision(False, unsafe_reason, {"path": path, "profile": profile})

    normalized = _normalize_repo_path(path)
    normalized_str = normalized.as_posix()
    basename = normalized.name
    suffix = Path(normalized_str).suffix.lower()

    if basename in ALLOWED_FILES:
        return PolicyDecision(True, "allowed file", {"path": normalized_str, "profile": profile})
    if any(normalized_str.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        return PolicyDecision(True, "allowed workflow path", {"path": normalized_str, "profile": profile})

    if suffix not in SUPPORTED_BENCHMARK_SUFFIXES and basename not in ALLOWED_FILES:
        return PolicyDecision(
            False,
            f"unsupported file type for {profile}: {normalized_str}",
            {"path": normalized_str, "profile": profile, "suffix": suffix},
        )

    if repo is None or not str(repo).strip():
        return PolicyDecision(
            False,
            f"repo required to validate supported file path: {normalized_str}",
            {"path": normalized_str, "profile": profile},
        )

    candidate = Path(repo).expanduser() / normalized_str
    if not candidate.exists():
        return PolicyDecision(
            False,
            f"supported benchmark patch must target an existing file: {normalized_str}",
            {"path": normalized_str, "profile": profile},
        )
    if not candidate.is_file():
        return PolicyDecision(
            False,
            f"supported benchmark patch must target a regular file: {normalized_str}",
            {"path": normalized_str, "profile": profile},
        )

    if profile == "strict" and not candidate.exists():
        return PolicyDecision(
            False,
            f"strict policy requires an existing file target: {normalized_str}",
            {"path": normalized_str, "profile": profile},
        )
    if profile == "strict" and not candidate.is_file():
        return PolicyDecision(
            False,
            f"strict policy requires a regular file target: {normalized_str}",
            {"path": normalized_str, "profile": profile},
        )

    return PolicyDecision(
        True,
        f"allowed supported file type ({suffix or basename})",
        {"path": normalized_str, "profile": profile, "suffix": suffix},
    )


def is_patch_allowed(path: str) -> PolicyDecision:
    return evaluate_patch_policy(path, profile="strict")


def is_command_allowed(cmd: str) -> PolicyDecision:
    c = cmd.lower()
    for bad in BANNED_COMMAND_SUBSTRINGS:
        if bad.lower() in c:
            return PolicyDecision(False, f"banned command pattern: {bad.strip()}")
    return PolicyDecision(True, "allowed command")
