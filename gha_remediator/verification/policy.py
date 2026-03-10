from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

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

BANNED_COMMAND_SUBSTRINGS = [
    "curl ",
    "wget ",
    "rm -rf /",
    "sudo rm",
    "printenv",
    "cat $GITHUB_TOKEN",
]

@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str

def is_patch_allowed(path: str) -> PolicyDecision:
    if path in ALLOWED_FILES:
        return PolicyDecision(True, "allowed file")
    if any(path.startswith(p) for p in ALLOWED_PATH_PREFIXES):
        return PolicyDecision(True, "allowed workflow path")
    return PolicyDecision(False, f"patch to disallowed path: {path}")

def is_command_allowed(cmd: str) -> PolicyDecision:
    c = cmd.lower()
    for bad in BANNED_COMMAND_SUBSTRINGS:
        if bad.lower() in c:
            return PolicyDecision(False, f"banned command pattern: {bad.strip()}")
    return PolicyDecision(True, "allowed command")
