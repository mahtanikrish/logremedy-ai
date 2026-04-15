from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import configparser
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from typing import Any, Iterable, Optional

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

try:
    from packaging.requirements import InvalidRequirement, Requirement
except Exception:
    InvalidRequirement = ValueError
    Requirement = None  # type: ignore[assignment]

from ..repo_context import preferred_node_manifest, preferred_node_workspace, preferred_workflow_path, primary_python_manifest
from ..types import RCAReport, RemediationPlan, RepoContext


CODESPELL_TIMEOUT_S = 15
WORKFLOW_TIMEOUT_S = 20
PYTEST_TIMEOUT_S = 45
PYTHON_QUALITY_TIMEOUT_S = 30
PYTHON_SOURCE_TIMEOUT_S = 20
SHELL_TIMEOUT_S = 15
UNSUPPORTED_REQUIREMENT_PREFIXES = (
    "-r",
    "--requirement",
    "-c",
    "--constraint",
    "-e",
    "--editable",
    "-f",
    "--find-links",
    "--index-url",
    "--extra-index-url",
    "--trusted-host",
    "--no-index",
    "--pre",
)


@dataclass(frozen=True)
class AdapterExecutionPlan:
    commands: list[str]
    workdir: str = "."
    source: str = "plan"


@dataclass(frozen=True)
class AdapterSelection:
    name: str
    reason: str
    execution: Optional[AdapterExecutionPlan] = None
    details: dict[str, Any] = field(default_factory=dict)
    matching_validators: list[str] = field(default_factory=list)
    suppressed_validators: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AdapterCheckResult:
    status: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    execution: Optional[AdapterExecutionPlan] = None
    availability: str = "available"
    summary: Optional[str] = None
    fallback_used: bool = False
    skip_sandbox: bool = False


def select_adapter(
    plan: RemediationPlan,
    *,
    report: Optional[RCAReport],
    repo_context: Optional[RepoContext],
    default_workdir: str = ".",
) -> AdapterSelection:
    touched = [patch.path for patch in plan.patches]
    report_text = _report_text(report)
    node_workspace = preferred_node_workspace(repo_context) or default_workdir
    matches: list[tuple[str, str, dict[str, Any], Optional[AdapterExecutionPlan]]] = []

    if (
        "codespell" in report_text
        or plan.fix_type == "spelling_correction"
    ):
        matches.append(
            (
                "codespell",
                "root cause indicates a codespell or spelling-correction failure",
                {"touched_paths": touched},
                None,
            )
        )

    workflow_targets = _resolve_workflow_targets(plan=plan, report=report, repo_context=repo_context)
    if workflow_targets:
        matches.append(
            (
                "workflow_yaml",
                "workflow files are touched or workflow configuration RCA resolved a unique workflow target",
                {"workflow_targets": workflow_targets, "touched_paths": touched},
                None,
            )
        )

    dep_manifest_targets = _resolve_dependency_manifest_targets(plan)
    if dep_manifest_targets:
        matches.append(
            (
                "python_dependency_manifest",
                "dependency-fix intent or dependency-manifest patch requires conservative manifest validation",
                {"manifest_targets": dep_manifest_targets, "touched_paths": touched},
                None,
            )
        )

    if _pytest_target_requested(plan, report):
        matches.append(
            (
                "pytest_target",
                "test failure signals require a grounded pytest target validator",
                {"touched_paths": touched},
                None,
            )
        )

    if _python_quality_target_requested(plan, report):
        matches.append(
            (
                "python_quality_target",
                "quality or formatter failure signals require a grounded Python file validator",
                {"touched_paths": touched},
                None,
            )
        )
 
    if _uses_node_commands(plan.commands):
        matches.append(
            (
                "node_workspace",
                "remediation requires Node package-manager commands",
                {"touched_paths": touched, "workdir": node_workspace, "commands": list(plan.commands)},
                None,
            )
        )

    if any(path.endswith(".sh") for path in touched):
        matches.append(
            (
                "shell_syntax",
                "patch touches a shell script",
                {"touched_paths": touched},
                None,
            )
        )

    if any(path.endswith(".py") for path in touched):
        matches.append(
            (
                "python_source",
                "patch touches Python source files",
                {"touched_paths": touched},
                None,
            )
        )

    if not matches:
        matches.append(
            (
                "generic",
                "no specialized deterministic adapter matched this plan",
                {"touched_paths": touched},
                None,
            )
        )

    selected_name, selected_reason, selected_details, selected_execution = matches[0]
    matching_validators = [name for name, _reason, _details, _execution in matches]
    suppressed_validators = matching_validators[1:]
    return AdapterSelection(
        name=selected_name,
        reason=selected_reason,
        execution=selected_execution,
        details=selected_details,
        matching_validators=matching_validators,
        suppressed_validators=suppressed_validators,
    )


def run_adapter_check(
    selection: AdapterSelection,
    *,
    patched_repo: str,
    plan: RemediationPlan,
    report: Optional[RCAReport],
    repo_context: Optional[RepoContext],
) -> AdapterCheckResult:
    if selection.name == "codespell":
        return _run_codespell_adapter(patched_repo=patched_repo, plan=plan, selection=selection)
    if selection.name == "workflow_yaml":
        return _run_workflow_yaml_adapter(patched_repo=patched_repo, selection=selection)
    if selection.name == "python_dependency_manifest":
        return _run_python_dependency_manifest_adapter(patched_repo=patched_repo, plan=plan, selection=selection)
    if selection.name == "pytest_target":
        return _run_pytest_target_adapter(patched_repo=patched_repo, plan=plan, report=report, repo_context=repo_context, selection=selection)
    if selection.name == "python_quality_target":
        return _run_python_quality_target_adapter(patched_repo=patched_repo, plan=plan, report=report, repo_context=repo_context, selection=selection)
    if selection.name == "shell_syntax":
        return _run_shell_syntax_adapter(patched_repo=patched_repo, plan=plan, selection=selection)
    if selection.name == "python_source":
        return _run_python_source_adapter(patched_repo=patched_repo, plan=plan, selection=selection)
    if selection.name == "node_workspace":
        return _run_node_workspace_adapter(selection=selection, repo_context=repo_context)
    return _run_generic_adapter(plan=plan, selection=selection)


def _run_codespell_adapter(
    *,
    patched_repo: str,
    plan: RemediationPlan,
    selection: AdapterSelection,
) -> AdapterCheckResult:
    tool = shutil.which("codespell")
    if tool is None:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator codespell is unavailable",
            summary="validator codespell is unavailable",
            availability="unavailable",
            details={"adapter": "codespell", **selection.details},
        )

    touched_files = [
        patch.path
        for patch in plan.patches
        if _is_text_file(patch.path) and os.path.exists(os.path.join(patched_repo, patch.path))
    ]
    if not touched_files:
        return AdapterCheckResult(
            status="skipped",
            reason="codespell adapter had no touched text files to inspect",
            summary="codespell validator was not needed",
            availability="not_needed",
            details={"adapter": "codespell", **selection.details},
        )

    completed = _run_command([tool, *touched_files], cwd=patched_repo, timeout_s=CODESPELL_TIMEOUT_S)
    if completed["status"] == "timeout":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator codespell could not validate this case",
            summary="validator codespell timed out",
            availability="reduced",
            details={"adapter": "codespell", **completed["details"]},
        )
    if completed["status"] != "ok":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator codespell could not validate this case",
            summary="validator codespell encountered a runtime error",
            availability="reduced",
            details={"adapter": "codespell", **completed["details"]},
        )

    result = completed["process"]
    details = {
        "adapter": "codespell",
        "touched_files": touched_files,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }
    if result.returncode == 0:
        return AdapterCheckResult(
            status="passed",
            reason="codespell reported no remaining spelling issues in touched files",
            summary="codespell validator passed",
            details=details,
        )
    return AdapterCheckResult(
        status="failed",
        reason="codespell still reports spelling issues in touched files",
        summary="codespell validator failed",
        details=details,
    )


def _run_workflow_yaml_adapter(
    *,
    patched_repo: str,
    selection: AdapterSelection,
) -> AdapterCheckResult:
    workflow_files = list(selection.details.get("workflow_targets", []))
    if not workflow_files:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator workflow_yaml could not validate this case",
            summary="no unique grounded workflow file was available",
            availability="reduced",
            details={"adapter": "workflow_yaml"},
        )

    if yaml is None:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator workflow_yaml is unavailable",
            summary="workflow_yaml validator unavailable because YAML parser is missing",
            availability="unavailable",
            details={"adapter": "workflow_yaml", "workflow_files": workflow_files},
        )

    for relpath in workflow_files:
        full_path = os.path.join(patched_repo, relpath)
        check = _workflow_fallback_check(full_path)
        if not check["ok"]:
            return AdapterCheckResult(
                status="failed",
                reason=f"workflow fallback validation failed: {check['msg']}",
                summary="workflow_yaml validator failed",
                details={"adapter": "workflow_yaml", "workflow_files": workflow_files, "check": check},
            )

    tool = shutil.which("actionlint")
    if tool is None:
        return AdapterCheckResult(
            status="passed",
            reason="workflow YAML fallback validation passed and actionlint is unavailable",
            summary="workflow_yaml validator ran in reduced mode",
            availability="reduced",
            fallback_used=True,
            details={"adapter": "workflow_yaml", "workflow_files": workflow_files, "actionlint_available": False},
        )

    completed = _run_command([tool, *workflow_files], cwd=patched_repo, timeout_s=WORKFLOW_TIMEOUT_S)
    if completed["status"] == "timeout":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator workflow_yaml could not validate this case",
            summary="validator workflow_yaml timed out",
            availability="reduced",
            details={"adapter": "workflow_yaml", **completed["details"]},
        )
    if completed["status"] != "ok":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator workflow_yaml could not validate this case",
            summary="validator workflow_yaml encountered a runtime error",
            availability="reduced",
            details={"adapter": "workflow_yaml", **completed["details"]},
        )

    process = completed["process"]
    details = {
        "adapter": "workflow_yaml",
        "workflow_files": workflow_files,
        "actionlint_available": True,
        "returncode": process.returncode,
        "stdout_tail": process.stdout[-2000:],
        "stderr_tail": process.stderr[-2000:],
    }
    if process.returncode == 0:
        return AdapterCheckResult(
            status="passed",
            reason="actionlint passed for grounded workflow files",
            summary="workflow_yaml validator passed",
            details=details,
        )
    return AdapterCheckResult(
        status="failed",
        reason="actionlint failed for grounded workflow files",
        summary="workflow_yaml validator failed",
        details=details,
    )


def _run_python_dependency_manifest_adapter(
    *,
    patched_repo: str,
    plan: RemediationPlan,
    selection: AdapterSelection,
) -> AdapterCheckResult:
    manifest_targets = list(selection.details.get("manifest_targets", []))
    if not manifest_targets:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_dependency_manifest could not validate this case",
            summary="no dependency manifest target was available",
            availability="reduced",
            details={"adapter": "python_dependency_manifest"},
        )

    patch_map = {patch.path: patch for patch in plan.patches}
    for relpath in manifest_targets:
        full_path = os.path.join(patched_repo, relpath)
        basename = Path(relpath).name
        patch = patch_map.get(relpath)
        if basename == "setup.py" and plan.fix_type in {"python_add_dependency", "python_pin_dependency"}:
            return AdapterCheckResult(
                status="inconclusive",
                reason="inconclusive because validator python_dependency_manifest could not validate this case",
                summary="setup.py dependency validation is unsupported",
                availability="reduced",
                details={"adapter": "python_dependency_manifest", "path": relpath},
            )
        if basename == "Pipfile":
            try:
                with open(full_path, "rb") as fh:
                    tomllib.load(fh)
            except Exception as exc:
                return AdapterCheckResult(
                    status="failed",
                    reason=f"Pipfile parse failed: {exc}",
                    summary="python_dependency_manifest validator failed",
                    details={"adapter": "python_dependency_manifest", "path": relpath},
                )
            continue
        if basename == "requirements.txt":
            requirement_result = _validate_requirements_patch(relpath, patch)
            if requirement_result is not None:
                return requirement_result
            continue
        if basename == "pyproject.toml":
            dependency_result = _validate_pyproject_dependencies(full_path, relpath, patch)
            if dependency_result is not None:
                return dependency_result
            continue
        if basename == "setup.cfg":
            dependency_result = _validate_setup_cfg_dependencies(full_path, relpath, patch)
            if dependency_result is not None:
                return dependency_result
            continue

    return AdapterCheckResult(
        status="passed",
        reason="dependency manifest validation passed",
        summary="python_dependency_manifest validator passed",
        details={"adapter": "python_dependency_manifest", "manifest_targets": manifest_targets},
    )


def _run_pytest_target_adapter(
    *,
    patched_repo: str,
    plan: RemediationPlan,
    report: Optional[RCAReport],
    repo_context: Optional[RepoContext],
    selection: AdapterSelection,
) -> AdapterCheckResult:
    tool = shutil.which("pytest")
    if tool is None:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator pytest_target is unavailable",
            summary="validator pytest_target is unavailable",
            availability="unavailable",
            details={"adapter": "pytest_target"},
        )

    command, workdir, target_resolution = _resolve_pytest_command(plan=plan, repo_root=patched_repo, repo_context=repo_context)
    if command is None:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator pytest_target could not validate this case",
            summary=target_resolution["summary"],
            availability="reduced",
            details={"adapter": "pytest_target", **target_resolution},
        )

    cwd = patched_repo if workdir in ("", ".") else os.path.join(patched_repo, workdir)
    completed = _run_command(command, cwd=cwd, timeout_s=PYTEST_TIMEOUT_S)
    if completed["status"] == "timeout":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator pytest_target could not validate this case",
            summary="validator pytest_target timed out",
            availability="reduced",
            details={"adapter": "pytest_target", **target_resolution, **completed["details"]},
            skip_sandbox=True,
        )
    if completed["status"] != "ok":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator pytest_target could not validate this case",
            summary="validator pytest_target encountered a runtime error",
            availability="reduced",
            details={"adapter": "pytest_target", **target_resolution, **completed["details"]},
            skip_sandbox=True,
        )

    process = completed["process"]
    details = {
        "adapter": "pytest_target",
        "command": command,
        "workdir": workdir,
        **target_resolution,
        "returncode": process.returncode,
        "stdout_tail": process.stdout[-2000:],
        "stderr_tail": process.stderr[-2000:],
    }
    if process.returncode == 0:
        return AdapterCheckResult(
            status="passed",
            reason="grounded pytest target passed",
            summary="pytest_target validator passed",
            details=details,
            skip_sandbox=True,
        )
    return AdapterCheckResult(
        status="failed",
        reason="grounded pytest target failed",
        summary="pytest_target validator failed",
        details=details,
        skip_sandbox=True,
    )


def _run_python_quality_target_adapter(
    *,
    patched_repo: str,
    plan: RemediationPlan,
    report: Optional[RCAReport],
    repo_context: Optional[RepoContext],
    selection: AdapterSelection,
) -> AdapterCheckResult:
    target, target_resolution = _resolve_python_quality_target(
        plan=plan,
        repo_root=patched_repo,
        repo_context=repo_context,
    )
    if target is None:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_quality_target could not validate this case",
            summary=target_resolution["summary"],
            availability="reduced",
            details={"adapter": "python_quality_target", **target_resolution},
        )

    quality_spec = _select_python_quality_validation(
        plan=plan,
        report=report,
        target=target,
    )
    if quality_spec is None:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_quality_target could not validate this case",
            summary="no narrow deterministic validator exists for the Python quality failure",
            availability="reduced",
            details={"adapter": "python_quality_target", **target_resolution},
        )

    details: dict[str, Any] = {
        "adapter": "python_quality_target",
        **target_resolution,
        "target": target,
        "validator": quality_spec["validator"],
        "validation_mode": "direct_tool",
    }
    completed = _run_tool_command(
        quality_spec["tool"],
        quality_spec["command"],
        cwd=patched_repo,
        timeout_s=PYTHON_QUALITY_TIMEOUT_S,
    )
    if completed["status"] == "missing":
        fallback = _maybe_run_pre_commit_fallback(
            target=target,
            cwd=patched_repo,
            details=details,
        )
        if fallback is not None:
            return fallback
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_quality_target is unavailable",
            summary=f"validator {quality_spec['validator']} is unavailable",
            availability="unavailable",
            details=details,
        )
    if completed["status"] == "timeout":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_quality_target could not validate this case",
            summary=f"validator {quality_spec['validator']} timed out",
            availability="reduced",
            details={**details, **completed["details"]},
            skip_sandbox=True,
        )
    if completed["status"] != "ok":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_quality_target could not validate this case",
            summary=f"validator {quality_spec['validator']} encountered a runtime error",
            availability="reduced",
            details={**details, **completed["details"]},
            skip_sandbox=True,
        )

    process = completed["process"]
    details.update(
        {
            "tool": quality_spec["tool"],
            "command": quality_spec["command"],
            "returncode": process.returncode,
            "stdout_tail": process.stdout[-2000:],
            "stderr_tail": process.stderr[-2000:],
        }
    )
    if quality_spec.get("stdout_must_be_empty") and process.stdout.strip():
        return AdapterCheckResult(
            status="failed",
            reason=f"{quality_spec['validator']} reported remaining formatting changes",
            summary="python_quality_target validator failed",
            details=details,
            skip_sandbox=True,
        )
    if process.returncode == 0:
        return AdapterCheckResult(
            status="passed",
            reason=f"{quality_spec['validator']} passed for grounded target {target}",
            summary="python_quality_target validator passed",
            details=details,
            skip_sandbox=True,
        )
    return AdapterCheckResult(
        status="failed",
        reason=f"{quality_spec['validator']} failed for grounded target {target}",
        summary="python_quality_target validator failed",
        details=details,
        skip_sandbox=True,
    )


def _run_shell_syntax_adapter(
    *,
    patched_repo: str,
    plan: RemediationPlan,
    selection: AdapterSelection,
) -> AdapterCheckResult:
    shell_files = [
        patch.path
        for patch in plan.patches
        if patch.path.endswith(".sh") and os.path.exists(os.path.join(patched_repo, patch.path))
    ]
    if not shell_files:
        return AdapterCheckResult(
            status="skipped",
            reason="shell adapter had no shell scripts to validate",
            summary="shell validator was not needed",
            availability="not_needed",
            details={"adapter": "shell_syntax", **selection.details},
        )

    for relpath in shell_files:
        completed = _run_command(["bash", "-n", relpath], cwd=patched_repo, timeout_s=SHELL_TIMEOUT_S)
        if completed["status"] == "timeout":
            return AdapterCheckResult(
                status="inconclusive",
                reason="inconclusive because validator shell_syntax could not validate this case",
                summary="validator shell_syntax timed out",
                availability="reduced",
                details={"adapter": "shell_syntax", **completed["details"]},
            )
        if completed["status"] != "ok":
            return AdapterCheckResult(
                status="inconclusive",
                reason="inconclusive because validator shell_syntax could not validate this case",
                summary="validator shell_syntax encountered a runtime error",
                availability="reduced",
                details={"adapter": "shell_syntax", **completed["details"]},
            )
        result = completed["process"]
        if result.returncode != 0:
            return AdapterCheckResult(
                status="failed",
                reason=f"bash -n failed for {relpath}",
                summary="shell_syntax validator failed",
                details={
                    "adapter": "shell_syntax",
                    "path": relpath,
                    "returncode": result.returncode,
                    "stdout_tail": result.stdout[-2000:],
                    "stderr_tail": result.stderr[-2000:],
                },
            )

    return AdapterCheckResult(
        status="passed",
        reason="bash -n passed for touched shell scripts",
        summary="shell_syntax validator passed",
        details={"adapter": "shell_syntax", "shell_files": shell_files},
    )


def _run_python_source_adapter(
    *,
    patched_repo: str,
    plan: RemediationPlan,
    selection: AdapterSelection,
) -> AdapterCheckResult:
    python_files = [
        patch.path
        for patch in plan.patches
        if patch.path.endswith(".py") and os.path.exists(os.path.join(patched_repo, patch.path))
    ]
    if not python_files:
        return AdapterCheckResult(
            status="skipped",
            reason="python adapter had no Python files to validate",
            summary="python_source validator was not needed",
            availability="not_needed",
            details={"adapter": "python_source", **selection.details},
        )

    completed = _run_command(
        [sys.executable, "-m", "compileall", "-q", *python_files],
        cwd=patched_repo,
        timeout_s=PYTHON_SOURCE_TIMEOUT_S,
    )
    if completed["status"] == "timeout":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_source could not validate this case",
            summary="validator python_source timed out",
            availability="reduced",
            details={"adapter": "python_source", **completed["details"]},
        )
    if completed["status"] != "ok":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_source could not validate this case",
            summary="validator python_source encountered a runtime error",
            availability="reduced",
            details={"adapter": "python_source", **completed["details"]},
        )
    result = completed["process"]
    details = {
        "adapter": "python_source",
        "python_files": python_files,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
    }
    if result.returncode == 0:
        return AdapterCheckResult(
            status="passed",
            reason="compileall passed for touched Python files",
            summary="python_source validator passed",
            details=details,
        )
    return AdapterCheckResult(
        status="failed",
        reason="compileall failed for touched Python files",
        summary="python_source validator failed",
        details=details,
    )


def _run_node_workspace_adapter(
    *,
    selection: AdapterSelection,
    repo_context: Optional[RepoContext],
) -> AdapterCheckResult:
    manifest = preferred_node_manifest(repo_context)
    if manifest is None:
        return AdapterCheckResult(
            status="failed",
            reason="node adapter could not find a package.json workspace to validate against",
            summary="node_workspace validator failed",
            details={"adapter": "node_workspace"},
        )

    scripts = repo_context.package_scripts.get(manifest, {}) if repo_context else {}
    workdir = selection.details.get("workdir") or preferred_node_workspace(repo_context) or "."
    commands = list(selection.details.get("commands", []))

    for command in commands:
        lowered = command.strip().lower()
        if lowered.startswith("npm run "):
            script = lowered.split()[2]
            if script not in scripts:
                return AdapterCheckResult(
                    status="failed",
                    reason=f"node adapter could not ground npm script {script!r} in {manifest}",
                    summary="node_workspace validator failed",
                    details={"adapter": "node_workspace", "manifest": manifest, "script": script},
                )
        elif lowered.startswith("pnpm run "):
            script = lowered.split()[2]
            if script not in scripts:
                return AdapterCheckResult(
                    status="failed",
                    reason=f"node adapter could not ground pnpm script {script!r} in {manifest}",
                    summary="node_workspace validator failed",
                    details={"adapter": "node_workspace", "manifest": manifest, "script": script},
                )

    return AdapterCheckResult(
        status="inconclusive",
        reason="inconclusive because validator node_workspace could not validate this case",
        summary="no narrow deterministic validator exists for the Node workspace commands",
        availability="reduced",
        details={"adapter": "node_workspace", "manifest": manifest, "workdir": workdir, "commands": commands},
    )


def _run_generic_adapter(
    *,
    plan: RemediationPlan,
    selection: AdapterSelection,
) -> AdapterCheckResult:
    if plan.commands:
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator generic could not validate this case",
            summary="no narrow deterministic validator exists for the planned commands",
            availability="reduced",
            details={
                "adapter": "generic",
                **selection.details,
                "commands": list(plan.commands),
                "command_scope": "broad_or_unsupported",
            },
        )
    return AdapterCheckResult(
        status="skipped",
        reason="no specialized adapter checks were required",
        summary="no specialized validator was needed",
        availability="not_needed",
        details={"adapter": "generic", **selection.details},
    )


def _resolve_workflow_targets(
    *,
    plan: RemediationPlan,
    report: Optional[RCAReport],
    repo_context: Optional[RepoContext],
) -> list[str]:
    touched = [
        patch.path
        for patch in plan.patches
        if patch.path.startswith(".github/workflows/") and patch.path.endswith((".yml", ".yaml"))
    ]
    if touched:
        return _dedupe_preserve_order(touched)
    if report is None or report.failure_class != "workflow_configuration_error" or repo_context is None:
        return []
    candidates = [
        candidate.path
        for candidate in repo_context.candidate_files
        if candidate.path.startswith(".github/workflows/")
    ]
    if len(candidates) == 1:
        return candidates
    preferred = preferred_workflow_path(repo_context)
    if preferred is not None:
        return [preferred]
    if len(repo_context.workflow_files) == 1:
        return [repo_context.workflow_files[0]]
    return []


def _python_quality_target_requested(plan: RemediationPlan, report: Optional[RCAReport]) -> bool:
    touched_python = any(path.endswith(".py") for path in (patch.path for patch in plan.patches))
    if not touched_python:
        return False
    text = _report_text(report)
    if any(keyword in text for keyword in ("ruff", "flake8", "isort", "yapf", "pre-commit", "i001", "w605")):
        return True
    return any(_is_broad_project_command(command) for command in plan.commands)


def _resolve_python_quality_target(
    *,
    plan: RemediationPlan,
    repo_root: str,
    repo_context: Optional[RepoContext],
) -> tuple[Optional[str], dict[str, Any]]:
    touched = [
        PurePosixPath(patch.path).as_posix()
        for patch in plan.patches
        if patch.path.endswith(".py") and os.path.exists(os.path.join(repo_root, patch.path))
    ]
    unique_touched = _dedupe_preserve_order(touched)
    if len(unique_touched) == 1:
        return unique_touched[0], {
            "resolution": "patched_python_file",
            "resolved_target": unique_touched[0],
            "summary": "grounded Python quality target resolved from the patched file",
        }
    if len(unique_touched) > 1:
        return None, {
            "resolution": "ambiguous_patched_files",
            "candidates": unique_touched,
            "summary": "multiple grounded Python files were patched",
        }

    candidates: list[str] = []
    for candidate in repo_context.candidate_files if repo_context else []:
        if not candidate.path.endswith(".py"):
            continue
        if os.path.exists(os.path.join(repo_root, candidate.path)):
            candidates.append(candidate.path)

    unique_candidates = _dedupe_preserve_order(candidates)
    if len(unique_candidates) == 1:
        return unique_candidates[0], {
            "resolution": "candidate_python_file",
            "resolved_target": unique_candidates[0],
            "summary": "grounded Python quality target resolved from repo context",
        }
    if not unique_candidates:
        return None, {
            "resolution": "none",
            "summary": "no grounded Python quality target",
        }
    return None, {
        "resolution": "ambiguous_candidate_files",
        "candidates": unique_candidates,
        "summary": "multiple grounded Python quality targets",
    }


def _select_python_quality_validation(
    *,
    plan: RemediationPlan,
    report: Optional[RCAReport],
    target: str,
) -> Optional[dict[str, Any]]:
    text = _report_text(report)
    command_text = " ".join(command.strip().lower() for command in plan.commands)
    if "ruff" in text or "i001" in text or "ruff" in command_text:
        command = ["check", target]
        if "i001" in text or "import" in text:
            command = ["check", "--select", "I", target]
        return {"validator": "ruff", "tool": "ruff", "command": command}
    if "isort" in text:
        return {"validator": "isort", "tool": "isort", "command": ["--check-only", "--diff", target]}
    if "flake8" in text or re.search(r"\b[wef]\d{3}\b", text) or "flake8" in command_text:
        return {"validator": "flake8", "tool": "flake8", "command": [target]}
    if "yapf" in text or "yapf" in command_text:
        return {
            "validator": "yapf",
            "tool": "yapf",
            "command": ["--diff", target],
            "stdout_must_be_empty": True,
        }
    if "pre-commit" in text or any(command.strip().lower().startswith("pre-commit") for command in plan.commands):
        return {"validator": "pre-commit", "tool": "pre-commit", "command": ["run", "--files", target]}
    return None


def _resolve_dependency_manifest_targets(plan: RemediationPlan) -> list[str]:
    touched = [patch.path for patch in plan.patches]
    basenames = {Path(path).name for path in touched}
    manifest_targets = [
        path
        for path in touched
        if Path(path).name in {"requirements.txt", "pyproject.toml", "setup.cfg", "Pipfile"}
    ]
    if plan.fix_type in {"python_add_dependency", "python_pin_dependency"} and "setup.py" in basenames:
        manifest_targets.extend(path for path in touched if Path(path).name == "setup.py")
    if plan.fix_type in {"python_add_dependency", "python_pin_dependency"} and not manifest_targets:
        manifest_targets.extend(path for path in touched if Path(path).name == "setup.py")
    return _dedupe_preserve_order(manifest_targets)


def _pytest_target_requested(plan: RemediationPlan, report: Optional[RCAReport]) -> bool:
    if report and report.failure_class == "test_failure":
        return True
    if report:
        text = " ".join(
            [
                report.root_cause_label or "",
                report.root_cause_text or "",
                *report.root_causes,
                *(line.text for line in report.key_lines[:50]),
            ]
        ).lower()
        if "pytest" in text:
            return True
    return any(command.strip().lower().startswith("pytest") for command in plan.commands)


def _resolve_pytest_command(
    *,
    plan: RemediationPlan,
    repo_root: str,
    repo_context: Optional[RepoContext],
) -> tuple[Optional[list[str]], str, dict[str, Any]]:
    for command in plan.commands:
        parsed = shlex.split(command)
        if not parsed or parsed[0] != "pytest":
            continue
        explicit_targets = [token for token in parsed[1:] if not token.startswith("-")]
        if len(explicit_targets) == 1:
            rel_target = explicit_targets[0]
            if os.path.exists(os.path.join(repo_root, rel_target)):
                workdir = _python_workdir(repo_context)
                return [shutil.which("pytest") or "pytest", rel_target], workdir, {
                    "resolved_target": rel_target,
                    "resolution": "explicit_planned_target",
                    "summary": "grounded pytest target selected from planned command",
                }

    candidates: list[str] = []
    for candidate in repo_context.candidate_files if repo_context else []:
        if not candidate.path.endswith(".py"):
            continue
        if _looks_like_pytest_target(candidate.path) and os.path.exists(os.path.join(repo_root, candidate.path)):
            candidates.append(candidate.path)

    if not candidates:
        for candidate in repo_context.candidate_files if repo_context else []:
            if not candidate.path.endswith(".py"):
                continue
            if _looks_like_pytest_target(candidate.path):
                continue
            if not os.path.exists(os.path.join(repo_root, candidate.path)):
                continue
            candidates.extend(
                existing
                for existing in _derive_pytest_targets(candidate.path)
                if os.path.exists(os.path.join(repo_root, existing))
            )

    unique_candidates = _dedupe_preserve_order(candidates)
    if len(unique_candidates) == 1:
        workdir = _python_workdir(repo_context)
        target = unique_candidates[0]
        return [shutil.which("pytest") or "pytest", target], workdir, {
            "resolved_target": target,
            "resolution": "derived_grounded_target",
            "summary": "grounded pytest target resolved from repo context",
        }
    if not unique_candidates:
        return None, _python_workdir(repo_context), {
            "resolution": "none",
            "summary": "no grounded pytest target",
        }
    return None, _python_workdir(repo_context), {
        "resolution": "ambiguous",
        "candidates": unique_candidates,
        "summary": "multiple grounded pytest targets",
    }


def _python_workdir(repo_context: Optional[RepoContext]) -> str:
    manifest = primary_python_manifest(repo_context)
    if manifest is None:
        return "."
    parent = PurePosixPath(manifest).parent.as_posix()
    return "." if parent == "." else parent


def _looks_like_pytest_target(path: str) -> bool:
    basename = Path(path).name
    return path.startswith("tests/") or basename.startswith("test_") or basename.endswith("_test.py")


def _derive_pytest_targets(source_path: str) -> Iterable[str]:
    pure = PurePosixPath(source_path)
    parent = pure.parent.as_posix()
    stem = pure.stem
    relative_parent = "" if parent == "." else parent
    candidates = [
        f"tests/test_{stem}.py",
        f"tests/{stem}_test.py",
        (PurePosixPath(relative_parent) / f"test_{stem}.py").as_posix() if relative_parent else f"test_{stem}.py",
        (PurePosixPath(relative_parent) / f"{stem}_test.py").as_posix() if relative_parent else f"{stem}_test.py",
    ]
    if relative_parent:
        candidates.extend(
            [
                (PurePosixPath("tests") / relative_parent / f"test_{stem}.py").as_posix(),
                (PurePosixPath("tests") / relative_parent / f"{stem}_test.py").as_posix(),
            ]
        )
    return candidates


def _validate_requirements_patch(relpath: str, patch) -> Optional[AdapterCheckResult]:
    changed_lines = _changed_noncomment_lines(patch)
    for line in changed_lines:
        if _requirement_line_unsupported(line):
            return AdapterCheckResult(
                status="inconclusive",
                reason="inconclusive because validator python_dependency_manifest could not validate this case",
                summary="unsupported dependency syntax in requirements.txt",
                availability="reduced",
                details={"adapter": "python_dependency_manifest", "path": relpath, "line": line},
            )
        parse_result = _parse_requirement_line(line)
        if parse_result is not None:
            return AdapterCheckResult(
                status=parse_result["status"],
                reason=parse_result["reason"],
                summary=parse_result["summary"],
                availability=parse_result["availability"],
                details={"adapter": "python_dependency_manifest", "path": relpath, "line": line},
            )
    return None


def _validate_pyproject_dependencies(full_path: str, relpath: str, patch) -> Optional[AdapterCheckResult]:
    with open(full_path, "rb") as fh:
        payload = tomllib.load(fh)
    dependency_values = set(payload.get("project", {}).get("dependencies", []) or [])
    optionals = payload.get("project", {}).get("optional-dependencies", {}) or {}
    for values in optionals.values():
        if isinstance(values, list):
            dependency_values.update(value for value in values if isinstance(value, str))

    added_strings = [value for value in _changed_quoted_strings(patch) if value in dependency_values]
    for value in added_strings:
        parse_result = _parse_requirement_line(value)
        if parse_result is not None:
            return AdapterCheckResult(
                status=parse_result["status"],
                reason=parse_result["reason"],
                summary=parse_result["summary"],
                availability=parse_result["availability"],
                details={"adapter": "python_dependency_manifest", "path": relpath, "line": value},
            )
    return None


def _validate_setup_cfg_dependencies(full_path: str, relpath: str, patch) -> Optional[AdapterCheckResult]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(full_path, encoding="utf-8")
    dependency_values: set[str] = set()
    if parser.has_option("options", "install_requires"):
        dependency_values.update(_split_multiline_values(parser.get("options", "install_requires")))
    for section in parser.sections():
        if section.startswith("options.extras_require"):
            for _name, value in parser.items(section):
                dependency_values.update(_split_multiline_values(value))

    changed_lines = _changed_noncomment_lines(patch)
    for line in changed_lines:
        if line not in dependency_values:
            continue
        if _requirement_line_unsupported(line):
            return AdapterCheckResult(
                status="inconclusive",
                reason="inconclusive because validator python_dependency_manifest could not validate this case",
                summary="unsupported dependency syntax in setup.cfg",
                availability="reduced",
                details={"adapter": "python_dependency_manifest", "path": relpath, "line": line},
            )
        parse_result = _parse_requirement_line(line)
        if parse_result is not None:
            return AdapterCheckResult(
                status=parse_result["status"],
                reason=parse_result["reason"],
                summary=parse_result["summary"],
                availability=parse_result["availability"],
                details={"adapter": "python_dependency_manifest", "path": relpath, "line": line},
            )
    return None


def _split_multiline_values(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip() and not line.strip().startswith("#")]


def _parse_requirement_line(line: str) -> Optional[dict[str, str]]:
    if Requirement is None:
        return {
            "status": "inconclusive",
            "reason": "inconclusive because validator python_dependency_manifest is unavailable",
            "summary": "validator python_dependency_manifest is unavailable",
            "availability": "unavailable",
        }
    try:
        Requirement(line)
        return None
    except InvalidRequirement:
        return {
            "status": "failed",
            "reason": "dependency requirement line is malformed",
            "summary": "python_dependency_manifest validator failed",
            "availability": "available",
        }


def _requirement_line_unsupported(line: str) -> bool:
    return line.startswith(UNSUPPORTED_REQUIREMENT_PREFIXES)


def _changed_noncomment_lines(patch) -> list[str]:
    out: list[str] = []
    for raw_line in patch.diff.splitlines():
        if raw_line.startswith(("+++", "@@", "---")):
            continue
        if not raw_line.startswith("+"):
            continue
        line = raw_line[1:].strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _changed_quoted_strings(patch) -> list[str]:
    values: list[str] = []
    for raw_line in patch.diff.splitlines():
        if raw_line.startswith(("+++", "@@", "---")) or not raw_line.startswith("+"):
            continue
        line = raw_line[1:].strip()
        if "\"" in line or "'" in line:
            quote = '"' if '"' in line else "'"
            parts = line.split(quote)
            if len(parts) >= 3:
                values.extend(part for idx, part in enumerate(parts[1::2], start=1) if part)
    return values


def _workflow_fallback_check(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh.read())
    except Exception as exc:
        return {"ok": False, "msg": f"yaml parse failed: {exc}"}
    if not isinstance(payload, dict):
        return {"ok": False, "msg": "workflow top-level document must be a mapping"}
    if "on" not in payload and "jobs" not in payload:
        return {"ok": False, "msg": "workflow must define at least one of 'on' or 'jobs'"}
    jobs = payload.get("jobs")
    if jobs is not None:
        if not isinstance(jobs, dict):
            return {"ok": False, "msg": "workflow jobs must be a mapping"}
        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                return {"ok": False, "msg": f"workflow job {job_name!r} must be a mapping"}
            steps = job.get("steps")
            if steps is not None:
                if not isinstance(steps, list):
                    return {"ok": False, "msg": f"workflow job {job_name!r} steps must be a list"}
                for index, step in enumerate(steps):
                    if not isinstance(step, dict):
                        return {"ok": False, "msg": f"workflow job {job_name!r} step {index} must be a mapping"}
    return {"ok": True, "msg": "workflow fallback validation passed"}


def _run_tool_command(
    tool_name: str,
    args: list[str],
    *,
    cwd: str,
    timeout_s: int,
) -> dict[str, Any]:
    tool = shutil.which(tool_name)
    if tool is None:
        return {"status": "missing", "details": {"tool": tool_name}}
    return _run_command([tool, *args], cwd=cwd, timeout_s=timeout_s)


def _maybe_run_pre_commit_fallback(
    *,
    target: str,
    cwd: str,
    details: dict[str, Any],
) -> Optional[AdapterCheckResult]:
    completed = _run_tool_command(
        "pre-commit",
        ["run", "--files", target],
        cwd=cwd,
        timeout_s=PYTHON_QUALITY_TIMEOUT_S,
    )
    if completed["status"] == "missing":
        return None
    if completed["status"] == "timeout":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_quality_target could not validate this case",
            summary="validator pre-commit timed out",
            availability="reduced",
            details={**details, **completed["details"], "validation_mode": "pre_commit_fallback"},
            fallback_used=True,
            skip_sandbox=True,
        )
    if completed["status"] != "ok":
        return AdapterCheckResult(
            status="inconclusive",
            reason="inconclusive because validator python_quality_target could not validate this case",
            summary="validator pre-commit encountered a runtime error",
            availability="reduced",
            details={**details, **completed["details"], "validation_mode": "pre_commit_fallback"},
            fallback_used=True,
            skip_sandbox=True,
        )
    process = completed["process"]
    fallback_details = {
        **details,
        "tool": "pre-commit",
        "command": ["pre-commit", "run", "--files", target],
        "validation_mode": "pre_commit_fallback",
        "returncode": process.returncode,
        "stdout_tail": process.stdout[-2000:],
        "stderr_tail": process.stderr[-2000:],
    }
    if process.returncode == 0:
        return AdapterCheckResult(
            status="passed",
            reason=f"pre-commit fallback passed for grounded target {target}",
            summary="python_quality_target validator passed",
            availability="reduced",
            details=fallback_details,
            fallback_used=True,
            skip_sandbox=True,
        )
    return AdapterCheckResult(
        status="failed",
        reason=f"pre-commit fallback failed for grounded target {target}",
        summary="python_quality_target validator failed",
        availability="reduced",
        details=fallback_details,
        fallback_used=True,
        skip_sandbox=True,
    )


def _run_command(cmd: list[str], *, cwd: str, timeout_s: int) -> dict[str, Any]:
    try:
        process = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {"status": "ok", "process": process}
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "details": {
                "timed_out": True,
                "cmd": cmd,
                "timeout_s": timeout_s,
                "stdout_tail": (exc.stdout or "")[-2000:],
                "stderr_tail": (exc.stderr or "")[-2000:],
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "details": {
                "cmd": cmd,
                "timeout_s": timeout_s,
                "error": str(exc),
            },
        }


def _uses_node_commands(commands: list[str]) -> bool:
    return any(command.strip().lower().startswith(("npm ", "pnpm ", "yarn ")) for command in commands)


def _is_broad_project_command(command: str) -> bool:
    try:
        parsed = shlex.split(command)
    except Exception:
        return True
    if not parsed:
        return False
    head = parsed[0].lower()
    if head in {"make", "tox", "nox"}:
        return True
    if head == "pre-commit" and "--files" not in parsed:
        return True
    if head == "pytest":
        explicit_targets = [token for token in parsed[1:] if not token.startswith("-")]
        return len(explicit_targets) != 1
    return False


def _report_text(report: Optional[RCAReport]) -> str:
    if report is None:
        return ""
    parts = [
        report.root_cause_label or "",
        report.root_cause_text or "",
        *report.root_causes,
        *(line.text for line in report.key_lines[:80]),
    ]
    return " ".join(part.lower() for part in parts if part)


def _is_text_file(path: str) -> bool:
    suffix = Path(PurePosixPath(path).as_posix()).suffix.lower()
    return suffix in {
        ".cfg",
        ".ini",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".py",
        ".rb",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
