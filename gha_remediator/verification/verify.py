from __future__ import annotations

from typing import Optional
import os

from ..types import RemediationPlan, VerificationResult
from .policy import is_patch_allowed, is_command_allowed
from .static_checks import file_exists, basic_static_validation
from .replay import replay_with_act, ReplayConfig
from .sandbox import verify_commands_locally
from .venv_verifier import verify_python_dependency


def verify_plan(
    plan: RemediationPlan,
    repo: str,
    replay_cfg: Optional[ReplayConfig] = None,
) -> VerificationResult:
    touched = [p.path for p in plan.patches]
    for path in touched:
        if not file_exists(repo, path):
            return VerificationResult(
                status="rejected_precondition",
                reason=f"file does not exist: {path}",
                evidence={"gate": "preconditions", "missing": path},
            )

    for p in plan.patches:
        dec = is_patch_allowed(p.path)
        if not dec.allowed:
            return VerificationResult(
                status="rejected_policy",
                reason=f"safety: {dec.reason}",
                evidence={"gate": "policy", "path": p.path},
            )

    for c in plan.commands:
        dec = is_command_allowed(c)
        if not dec.allowed:
            return VerificationResult(
                status="rejected_policy",
                reason=f"safety: {dec.reason}",
                evidence={"gate": "policy", "command": c},
            )

    static = basic_static_validation(repo, touched)
    for chk in static.get("checks", []):
        if chk.get("ok") is False:
            return VerificationResult(
                status="rejected_static",
                reason=f"static validation failed: {chk.get('msg')}",
                evidence={"gate": "static", "checks": static["checks"]},
            )

    _python_dep_fixes = ("python_add_dependency", "python_pin_dependency")
    if plan.fix_type in _python_dep_fixes:
        pkg = (
            plan.evidence.get("extracted", {}).get("module")
            or plan.evidence.get("extracted", {}).get("package")
        )
        if pkg:
            status, ev = verify_python_dependency(pkg)
            if status == "failed":
                return VerificationResult(
                    status="failed_replay",
                    reason=f"venv sandbox: pip install {pkg!r} failed",
                    evidence={"gate": "venv_sandbox", **ev},
                )
    elif plan.commands:
        status, ev = verify_commands_locally(plan.commands, repo)
        if status == "failed":
            return VerificationResult(
                status="failed_replay",
                reason="local sandbox command failed",
                evidence={"gate": "sandbox", **ev},
            )

    if replay_cfg is None:
        return VerificationResult(
            status="inconclusive",
            reason="replay not configured",
            evidence={"gate": "replay", "static": static},
        )

    status, ev = replay_with_act(repo, replay_cfg)

    if status == "verified":
        return VerificationResult(
            status="verified",
            reason="replay passed",
            evidence={"gate": "replay", **ev, "static": static},
        )

    if status == "failed":
        return VerificationResult(
            status="failed_replay",
            reason="replay failed",
            evidence={"gate": "replay", **ev, "static": static},
        )

    return VerificationResult(
        status="inconclusive",
        reason=ev.get("reason", "replay inconclusive"),
        evidence={"gate": "replay", **ev, "static": static},
    )
