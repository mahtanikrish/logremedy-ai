from __future__ import annotations

from typing import Optional, Any, Dict, List
import os

from ..types import RCAReport, RemediationPlan, RepoContext, VerificationResult
from .adapters import AdapterCheckResult, AdapterSelection, run_adapter_check, select_adapter
from .capability import build_capability, capability_from_selection, early_exit_capability
from .grounding import evaluate_grounding
from .policy import (
    VerificationProfile,
    evaluate_patch_budget,
    evaluate_patch_policy,
    is_command_allowed,
)
from .replay import ReplayConfig, replay_skipped_evidence, replay_with_act
from .sandbox import verify_commands_locally
from .static_checks import basic_static_validation
from .venv_verifier import verify_python_dependency
from .workspace import (
    WorkspacePreparationError,
    apply_plan_patches,
    prepare_workspace_copy,
)


GATE_ORDER = (
    "preconditions",
    "policy",
    "grounding",
    "patch_apply",
    "static",
    "adapter_check",
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
    capability: Dict[str, Any],
    static: Optional[Dict[str, Any]] = None,
    replay: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    evidence: Dict[str, Any] = {
        "gate": terminal_gate,
        "gates": _completed_gates(gates, terminal_gate),
        "capability": capability,
    }
    if static is not None:
        evidence["static"] = static
    if replay is not None:
        evidence["replay"] = replay
    if extra:
        evidence.update(extra)
    return evidence


def _result(
    *,
    status: str,
    reason: str,
    terminal_gate: str,
    gates: List[Dict[str, Any]],
    capability: Dict[str, Any],
    static: Optional[Dict[str, Any]] = None,
    replay: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> VerificationResult:
    return VerificationResult(
        status=status,
        reason=reason,
        evidence=_build_evidence(
            terminal_gate=terminal_gate,
            gates=gates,
            capability=capability,
            static=static,
            replay=replay,
            extra=extra,
        ),
    )


def _gate_status_from_verifier(status: str) -> str:
    if status == "verified":
        return "passed"
    if status == "failed":
        return "failed"
    return "inconclusive"


def _selection_metadata(selection: AdapterSelection) -> Dict[str, Any]:
    return {
        "name": selection.name,
        "reason": selection.reason,
        "matching_validators": selection.matching_validators,
        "suppressed_validators": selection.suppressed_validators,
    }


def _accepted_reason(adapter_result: AdapterCheckResult, selection: AdapterSelection) -> str:
    if adapter_result.availability == "reduced" or adapter_result.fallback_used:
        return f"accepted under reduced validator {selection.name}"
    return f"accepted under supported validator {selection.name}"


def _inconclusive_reason(selection: AdapterSelection, adapter_result: AdapterCheckResult) -> str:
    if adapter_result.availability == "unavailable":
        return f"inconclusive because validator {selection.name} is unavailable"
    return f"inconclusive because validator {selection.name} could not validate this case"


def verify_plan(
    plan: RemediationPlan,
    repo: str,
    replay_cfg: Optional[ReplayConfig] = None,
    verification_profile: VerificationProfile = "strict",
    report: Optional[RCAReport] = None,
    repo_context: Optional[RepoContext] = None,
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
            capability=early_exit_capability(summary="verification rejected at preconditions"),
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
            capability=early_exit_capability(summary="verification rejected at preconditions"),
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
                capability=early_exit_capability(summary="verification rejected by policy"),
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
                    capability=early_exit_capability(summary="verification rejected by policy"),
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
                    capability=early_exit_capability(summary="verification rejected by policy"),
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

        if not plan.patches and not plan.commands:
            gates.append(
                _gate_result(
                    "grounding",
                    "failed",
                    "remediation plan has no actionable patches or commands",
                    {"fix_type": plan.fix_type},
                )
            )
            return _result(
                status="rejected_unappliable",
                reason="remediation plan has no actionable patches or commands",
                terminal_gate="grounding",
                gates=gates,
                capability=early_exit_capability(summary="verification rejected because remediation plan is empty"),
                extra={"fix_type": plan.fix_type},
            )

        grounding = evaluate_grounding(
            plan,
            repo=repo,
            report=report,
            repo_context=repo_context,
        )
        if not grounding.allowed:
            gates.append(
                _gate_result(
                    "grounding",
                    "failed",
                    grounding.reason,
                    grounding.details,
                )
            )
            return _result(
                status="rejected_grounding",
                reason=grounding.reason,
                terminal_gate="grounding",
                gates=gates,
                capability=early_exit_capability(summary="verification rejected by grounding"),
                extra=grounding.details,
            )

        gates.append(
            _gate_result(
                "grounding",
                "passed",
                grounding.reason,
                {**grounding.details, "sandbox_workdir": grounding.sandbox_workdir},
            )
        )

        try:
            patch_apply = apply_plan_patches(workspace, plan)
        except WorkspacePreparationError as err:
            gates.append(_gate_result("patch_apply", "failed", err.reason, err.details))
            return _result(
                status="rejected_unappliable",
                reason=err.reason,
                terminal_gate="patch_apply",
                gates=gates,
                capability=early_exit_capability(summary="verification rejected because patch did not apply"),
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
                capability=build_capability(
                    selected_validator="static",
                    selection_reason="deterministic static validation failed before adapter execution",
                    matching_validators=[],
                    suppressed_validators=[],
                    availability="available",
                    outcome="rejected",
                    summary="verification rejected by static validation",
                    execution_mode="deterministic",
                    fallback_used=False,
                ),
                static=static,
                extra={"checks": static_checks},
            )

        if static_checks:
            gates.append(
                _gate_result(
                    "static",
                    "passed",
                    "static validation completed",
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

        selection = select_adapter(
            plan,
            report=report,
            repo_context=repo_context,
            default_workdir=grounding.sandbox_workdir,
        )
        adapter_result = run_adapter_check(
            selection,
            patched_repo=workspace.patched_repo,
            plan=plan,
            report=report,
            repo_context=repo_context,
        )
        gates.append(
            _gate_result(
                "adapter_check",
                adapter_result.status,
                adapter_result.reason,
                {
                    **adapter_result.details,
                    "adapter": selection.name,
                    "adapter_reason": selection.reason,
                    "matching_validators": selection.matching_validators,
                    "suppressed_validators": selection.suppressed_validators,
                    "availability": adapter_result.availability,
                    "fallback_used": adapter_result.fallback_used,
                },
            )
        )

        selection_meta = _selection_metadata(selection)

        if adapter_result.status == "failed":
            return _result(
                status="rejected_adapter_check",
                reason=adapter_result.reason,
                terminal_gate="adapter_check",
                gates=gates,
                capability=capability_from_selection(
                    selection_meta,
                    availability=adapter_result.availability,
                    outcome="rejected",
                    summary=adapter_result.summary or "validator failed",
                    execution_mode="deterministic",
                    fallback_used=adapter_result.fallback_used,
                ),
                static=static,
                extra=adapter_result.details,
            )

        if adapter_result.status == "inconclusive":
            replay = replay_skipped_evidence(
                reason=adapter_result.summary or adapter_result.reason,
                cfg=replay_cfg,
                repo=workspace.patched_repo,
            )
            return _result(
                status="inconclusive",
                reason=_inconclusive_reason(selection, adapter_result),
                terminal_gate="replay",
                gates=gates,
                capability=capability_from_selection(
                    selection_meta,
                    availability=adapter_result.availability,
                    outcome="inconclusive",
                    summary=adapter_result.summary or "validator could not validate this case",
                    execution_mode="deterministic",
                    fallback_used=adapter_result.fallback_used,
                ),
                static=static,
                replay=replay,
                extra=adapter_result.details,
            )

        execution_commands: List[str] = []
        execution_workdir = grounding.sandbox_workdir
        if adapter_result.execution is not None:
            execution_workdir = adapter_result.execution.workdir or execution_workdir
            if adapter_result.execution.commands:
                execution_commands = list(adapter_result.execution.commands)
        elif selection.execution is not None:
            execution_workdir = selection.execution.workdir or execution_workdir
            if selection.execution.commands:
                execution_commands = list(selection.execution.commands)

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
                    replay = replay_skipped_evidence(
                        reason="sandbox execution failed",
                        cfg=replay_cfg,
                        repo=workspace.patched_repo,
                    )
                    return _result(
                        status="rejected_execution",
                        reason="local sandbox command failed",
                        terminal_gate="sandbox",
                        gates=gates,
                        capability=capability_from_selection(
                            selection_meta,
                            availability=adapter_result.availability,
                            outcome="rejected",
                            summary="sandbox execution failed",
                            execution_mode="deterministic",
                            fallback_used=adapter_result.fallback_used,
                        ),
                        static=static,
                        replay=replay,
                        extra={"mode": "venv", **ev},
                    )
                if status == "inconclusive":
                    replay = replay_skipped_evidence(
                        reason="sandbox execution was inconclusive",
                        cfg=replay_cfg,
                        repo=workspace.patched_repo,
                    )
                    return _result(
                        status="inconclusive",
                        reason="inconclusive because sandbox execution could not validate this case",
                        terminal_gate="sandbox",
                        gates=gates,
                        capability=capability_from_selection(
                            selection_meta,
                            availability=adapter_result.availability,
                            outcome="inconclusive",
                            summary="sandbox execution was inconclusive",
                            execution_mode="deterministic",
                            fallback_used=adapter_result.fallback_used,
                        ),
                        static=static,
                        replay=replay,
                        extra={"mode": "venv", **ev},
                    )
            elif execution_commands:
                sandbox_repo = workspace.clone_for_gate("sandbox")
                status, ev = verify_commands_locally(
                    execution_commands,
                    sandbox_repo,
                    workdir=execution_workdir,
                )
                gates.append(
                    _gate_result(
                        "sandbox",
                        _gate_status_from_verifier(status),
                        "sandbox command verification completed",
                        ev,
                    )
                )
                if status == "failed":
                    replay = replay_skipped_evidence(
                        reason="sandbox execution failed",
                        cfg=replay_cfg,
                        repo=workspace.patched_repo,
                    )
                    return _result(
                        status="rejected_execution",
                        reason="local sandbox command failed",
                        terminal_gate="sandbox",
                        gates=gates,
                        capability=capability_from_selection(
                            selection_meta,
                            availability=adapter_result.availability,
                            outcome="rejected",
                            summary="sandbox execution failed",
                            execution_mode="deterministic",
                            fallback_used=adapter_result.fallback_used,
                        ),
                        static=static,
                        replay=replay,
                        extra=ev,
                    )
                if status == "inconclusive":
                    replay = replay_skipped_evidence(
                        reason="sandbox execution was inconclusive",
                        cfg=replay_cfg,
                        repo=workspace.patched_repo,
                    )
                    return _result(
                        status="inconclusive",
                        reason="inconclusive because sandbox execution could not validate this case",
                        terminal_gate="sandbox",
                        gates=gates,
                        capability=capability_from_selection(
                            selection_meta,
                            availability=adapter_result.availability,
                            outcome="inconclusive",
                            summary="sandbox execution was inconclusive",
                            execution_mode="deterministic",
                            fallback_used=adapter_result.fallback_used,
                        ),
                        static=static,
                        replay=replay,
                        extra=ev,
                    )
            else:
                gates.append(_gate_result("sandbox", "skipped", "no sandbox verification available"))
        elif adapter_result.skip_sandbox:
            gates.append(_gate_result("sandbox", "skipped", "adapter performed execution validation"))
        elif execution_commands:
            sandbox_repo = workspace.clone_for_gate("sandbox")
            status, ev = verify_commands_locally(
                execution_commands,
                sandbox_repo,
                workdir=execution_workdir,
            )
            gates.append(
                _gate_result(
                    "sandbox",
                    _gate_status_from_verifier(status),
                    "sandbox command verification completed",
                    ev,
                )
            )
            if status == "failed":
                replay = replay_skipped_evidence(
                    reason="sandbox execution failed",
                    cfg=replay_cfg,
                    repo=workspace.patched_repo,
                )
                return _result(
                    status="rejected_execution",
                    reason="local sandbox command failed",
                    terminal_gate="sandbox",
                    gates=gates,
                    capability=capability_from_selection(
                        selection_meta,
                        availability=adapter_result.availability,
                        outcome="rejected",
                        summary="sandbox execution failed",
                        execution_mode="deterministic",
                        fallback_used=adapter_result.fallback_used,
                    ),
                    static=static,
                    replay=replay,
                    extra=ev,
                )
            if status == "inconclusive":
                replay = replay_skipped_evidence(
                    reason="sandbox execution was inconclusive",
                    cfg=replay_cfg,
                    repo=workspace.patched_repo,
                )
                return _result(
                    status="inconclusive",
                    reason="inconclusive because sandbox execution could not validate this case",
                    terminal_gate="sandbox",
                    gates=gates,
                    capability=capability_from_selection(
                        selection_meta,
                        availability=adapter_result.availability,
                        outcome="inconclusive",
                        summary="sandbox execution was inconclusive",
                        execution_mode="deterministic",
                        fallback_used=adapter_result.fallback_used,
                    ),
                    static=static,
                    replay=replay,
                    extra=ev,
                )
        else:
            gates.append(_gate_result("sandbox", "skipped", "no commands to verify"))

        accepted_reason = _accepted_reason(adapter_result, selection)
        accepted_capability = capability_from_selection(
            selection_meta,
            availability=adapter_result.availability,
            outcome="accepted",
            summary=adapter_result.summary or f"{selection.name} validator passed",
            execution_mode="deterministic",
            fallback_used=adapter_result.fallback_used,
        )

        if replay_cfg is None:
            replay = replay_skipped_evidence(
                reason="replay not configured",
                cfg=None,
                repo=workspace.patched_repo,
            )
            gates.append(_gate_result("replay", "skipped", "replay not configured", replay))
            return _result(
                status="accepted",
                reason=accepted_reason,
                terminal_gate="replay",
                gates=gates,
                capability=accepted_capability,
                static=static,
                replay=replay,
            )

        if not plan.patches:
            replay = replay_skipped_evidence(
                reason="replay skipped: no persistent patched repo state",
                cfg=replay_cfg,
                repo=workspace.patched_repo,
            )
            gates.append(
                _gate_result(
                    "replay",
                    "skipped",
                    "replay skipped: no persistent patched repo state",
                    replay,
                )
            )
            return _result(
                status="accepted",
                reason=accepted_reason,
                terminal_gate="replay",
                gates=gates,
                capability=accepted_capability,
                static=static,
                replay=replay,
                extra={"commands": execution_commands},
            )

        replay_repo = workspace.clone_for_gate("replay")
        status, replay = replay_with_act(replay_repo, replay_cfg)
        gates.append(
            _gate_result(
                "replay",
                _gate_status_from_verifier(status),
                replay.get("classification", "replay finished"),
                replay,
            )
        )

        if status == "verified":
            return _result(
                status="verified",
                reason="replay passed",
                terminal_gate="replay",
                gates=gates,
                capability=capability_from_selection(
                    selection_meta,
                    availability=adapter_result.availability,
                    outcome="verified",
                    summary=adapter_result.summary or f"{selection.name} validator passed",
                    execution_mode="replay",
                    fallback_used=adapter_result.fallback_used,
                ),
                static=static,
                replay=replay,
            )

        if status == "failed":
            return _result(
                status="failed_replay",
                reason="replay failed",
                terminal_gate="replay",
                gates=gates,
                capability=capability_from_selection(
                    selection_meta,
                    availability=adapter_result.availability,
                    outcome="rejected",
                    summary="deterministic validation passed, but replay failed",
                    execution_mode="replay",
                    fallback_used=adapter_result.fallback_used,
                ),
                static=static,
                replay=replay,
            )

        return _result(
            status="accepted",
            reason=accepted_reason,
            terminal_gate="replay",
            gates=gates,
            capability=accepted_capability,
            static=static,
            replay=replay,
        )
