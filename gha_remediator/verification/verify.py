from __future__ import annotations

from typing import Optional, Any, Dict, List
import os

from ..types import RemediationPlan, VerificationResult
from .policy import (
    VerificationProfile,
    evaluate_patch_budget,
    evaluate_patch_policy,
    is_command_allowed,
)
from .static_checks import basic_static_validation
from .replay import replay_with_act, ReplayConfig
from .sandbox import verify_commands_locally
from .venv_verifier import verify_python_dependency
from .workspace import (
    WorkspacePreparationError,
    apply_plan_patches,
    prepare_workspace_copy,
)


GATE_ORDER = (
    "preconditions",
    "policy",
    "patch_apply",
    "static",
    "sandbox",
    "replay",
)

PYTHON_DEP_FIXES = ("python_add_dependency", "python_pin_dependency")


def _gate_result(
    name: str,
    status: str,
    reason: str,
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "details": details or {},
    }


def _completed_gates(gates: List[Dict[str, Any]], terminal_gate: str) -> List[Dict[str, Any]]:
    gate_map = {gate["name"]: gate for gate in gates}
    terminal_index = GATE_ORDER.index(terminal_gate)
    completed: List[Dict[str, Any]] = []
    for index, name in enumerate(GATE_ORDER):
        if name in gate_map:
            completed.append(gate_map[name])
            continue
        if index > terminal_index:
            completed.append(_gate_result(name, "skipped", "not reached"))
    return completed


def _build_evidence(
    *,
    terminal_gate: str,
    gates: List[Dict[str, Any]],
    static: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "gate": terminal_gate,
        "gates": _completed_gates(gates, terminal_gate),
    }
    if static is not None:
        evidence["static"] = static
    if extra:
        evidence.update(extra)
    return evidence


def _result(
    *,
    status: str,
    reason: str,
    terminal_gate: str,
    gates: List[Dict[str, Any]],
    static: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> VerificationResult:
    return VerificationResult(
        status=status,
        reason=reason,
        evidence=_build_evidence(
            terminal_gate=terminal_gate,
            gates=gates,
            static=static,
            extra=extra,
        ),
    )


def _gate_status_from_verifier(status: str) -> str:
    if status == "verified":
        return "passed"
    if status == "failed":
        return "failed"
    return "inconclusive"


def verify_plan(
    plan: RemediationPlan,
    repo: str,
    replay_cfg: Optional[ReplayConfig] = None,
    verification_profile: VerificationProfile = "strict",
) -> VerificationResult:
    gates: List[Dict[str, Any]] = []
    touched = [p.path for p in plan.patches]
    if not os.path.isdir(repo):
        gates.append(
            _gate_result(
                "preconditions",
                "failed",
                f"repo does not exist: {repo}",
                {"repo": repo, "repo_exists": False},
            )
        )
        return _result(
            status="rejected_precondition",
            reason=f"repo does not exist: {repo}",
            terminal_gate="preconditions",
            gates=gates,
            extra={"repo": repo, "repo_exists": False},
        )

    try:
        workspace = prepare_workspace_copy(repo)
    except WorkspacePreparationError as err:
        gates.append(_gate_result("preconditions", "failed", err.reason, err.details))
        return _result(
            status="rejected_precondition",
            reason=err.reason,
            terminal_gate="preconditions",
            gates=gates,
            extra=err.details,
        )

    gates.append(
        _gate_result(
            "preconditions",
            "passed",
            "verification workspace prepared",
            {"repo": repo, "touched_paths": touched},
        )
    )

    with workspace:
        budget_decision = evaluate_patch_budget(plan.patches, profile=verification_profile)
        if not budget_decision.allowed:
            gates.append(
                _gate_result(
                    "policy",
                    "failed",
                    f"safety: {budget_decision.reason}",
                    budget_decision.details,
                )
            )
            return _result(
                status="rejected_policy",
                reason=f"safety: {budget_decision.reason}",
                terminal_gate="policy",
                gates=gates,
                extra=budget_decision.details,
            )

        for p in plan.patches:
            dec = evaluate_patch_policy(
                p.path,
                repo=repo,
                profile=verification_profile,
            )
            if not dec.allowed:
                gates.append(
                    _gate_result(
                        "policy",
                        "failed",
                        f"safety: {dec.reason}",
                        dec.details or {"path": p.path},
                    )
                )
                return _result(
                    status="rejected_policy",
                    reason=f"safety: {dec.reason}",
                    terminal_gate="policy",
                    gates=gates,
                    extra=dec.details or {"path": p.path},
                )

        for c in plan.commands:
            dec = is_command_allowed(c)
            if not dec.allowed:
                gates.append(
                    _gate_result(
                        "policy",
                        "failed",
                        f"safety: {dec.reason}",
                        {"command": c},
                    )
                )
                return _result(
                    status="rejected_policy",
                    reason=f"safety: {dec.reason}",
                    terminal_gate="policy",
                    gates=gates,
                    extra={"command": c},
                )

        gates.append(
            _gate_result(
                "policy",
                "passed",
                "policy checks passed",
                {
                    "patches_checked": len(plan.patches),
                    "commands_checked": len(plan.commands),
                    "verification_profile": verification_profile,
                },
            )
        )

        try:
            patch_apply = apply_plan_patches(workspace, plan)
        except WorkspacePreparationError as err:
            gates.append(_gate_result("patch_apply", "failed", err.reason, err.details))
            return _result(
                status="rejected_precondition",
                reason=err.reason,
                terminal_gate="patch_apply",
                gates=gates,
                extra=err.details,
            )

        gates.append(
            _gate_result(
                "patch_apply",
                patch_apply["status"],
                patch_apply["reason"],
                patch_apply["details"],
            )
        )

        static = basic_static_validation(workspace.patched_repo, touched)
        static_checks = static.get("checks", [])
        if static_checks:
            first_failure = next((chk for chk in static_checks if chk.get("ok") is False), None)
            if first_failure is not None:
                gates.append(
                    _gate_result(
                        "static",
                        "failed",
                        f"static validation failed: {first_failure.get('msg')}",
                        {"checks": static_checks},
                    )
                )
                return _result(
                    status="rejected_static",
                    reason=f"static validation failed: {first_failure.get('msg')}",
                    terminal_gate="static",
                    gates=gates,
                    static=static,
                    extra={"checks": static_checks},
                )

            gates.append(
                _gate_result(
                    "static",
                    "passed",
                    "static validation passed",
                    {"checks": static_checks},
                )
            )
        else:
            gates.append(
                _gate_result(
                    "static",
                    "skipped",
                    "no applicable static checks",
                    {"touched_paths": touched},
                )
            )

        if plan.fix_type in PYTHON_DEP_FIXES:
            pkg = (
                plan.evidence.get("extracted", {}).get("module")
                or plan.evidence.get("extracted", {}).get("package")
            )
            if pkg:
                status, ev = verify_python_dependency(pkg)
                gates.append(
                    _gate_result(
                        "sandbox",
                        _gate_status_from_verifier(status),
                        f"venv verification for {pkg}",
                        {"mode": "venv", **ev},
                    )
                )
                if status == "failed":
                    return _result(
                        status="failed_replay",
                        reason=f"venv sandbox: pip install {pkg!r} failed",
                        terminal_gate="sandbox",
                        gates=gates,
                        static=static,
                        extra={"mode": "venv", **ev},
                    )
            elif plan.commands:
                sandbox_repo = workspace.clone_for_gate("sandbox")
                status, ev = verify_commands_locally(plan.commands, sandbox_repo)
                gates.append(
                    _gate_result(
                        "sandbox",
                        _gate_status_from_verifier(status),
                        "sandbox command verification completed",
                        ev,
                    )
                )
                if status == "failed":
                    return _result(
                        status="failed_replay",
                        reason="local sandbox command failed",
                        terminal_gate="sandbox",
                        gates=gates,
                        static=static,
                        extra=ev,
                    )
            else:
                gates.append(_gate_result("sandbox", "skipped", "no sandbox verification available"))
        elif plan.commands:
            sandbox_repo = workspace.clone_for_gate("sandbox")
            status, ev = verify_commands_locally(plan.commands, sandbox_repo)
            gates.append(
                _gate_result(
                    "sandbox",
                    _gate_status_from_verifier(status),
                    "sandbox command verification completed",
                    ev,
                )
            )
            if status == "failed":
                return _result(
                    status="failed_replay",
                    reason="local sandbox command failed",
                    terminal_gate="sandbox",
                    gates=gates,
                    static=static,
                    extra=ev,
                )
        else:
            gates.append(_gate_result("sandbox", "skipped", "no commands to verify"))

        if replay_cfg is None:
            gates.append(_gate_result("replay", "skipped", "replay not configured"))
            return _result(
                status="inconclusive",
                reason="replay not configured",
                terminal_gate="replay",
                gates=gates,
                static=static,
            )

        if not plan.patches:
            gates.append(
                _gate_result(
                    "replay",
                    "skipped",
                    "replay skipped: no persistent patched repo state",
                    {"commands": plan.commands},
                )
            )
            return _result(
                status="inconclusive",
                reason="replay skipped: no persistent patched repo state",
                terminal_gate="replay",
                gates=gates,
                static=static,
                extra={"commands": plan.commands},
            )

        replay_repo = workspace.clone_for_gate("replay")
        status, ev = replay_with_act(replay_repo, replay_cfg)
        gates.append(
            _gate_result(
                "replay",
                _gate_status_from_verifier(status),
                ev.get("reason", "replay finished"),
                ev,
            )
        )

        if status == "verified":
            return _result(
                status="verified",
                reason="replay passed",
                terminal_gate="replay",
                gates=gates,
                static=static,
                extra=ev,
            )

        if status == "failed":
            return _result(
                status="failed_replay",
                reason="replay failed",
                terminal_gate="replay",
                gates=gates,
                static=static,
                extra=ev,
            )

        return _result(
            status="inconclusive",
            reason=ev.get("reason", "replay inconclusive"),
            terminal_gate="replay",
            gates=gates,
            static=static,
            extra=ev,
        )
