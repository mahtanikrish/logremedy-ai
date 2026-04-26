from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import re

from ..repo_context import (
    detect_primary_package_manager,
    preferred_workflow_path,
    primary_python_manifest,
)
from ..types import RCAReport, RemediationPlan, Patch, FailureClass, RepoContext

@dataclass(frozen=True)
class TemplateMatch:
    fix_type: str
    score: float
    extracted: Dict[str, Any]

def _extract_missing_module(text: str) -> Optional[str]:
    m = re.search(r"no module named\s+['\"]?([a-zA-Z0-9_\-\.]+)['\"]?", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return None

def _extract_no_matching_dist(text: str) -> Optional[str]:
    m = re.search(r"could not find a version that satisfies the requirement\s+([a-zA-Z0-9_\-\.]+)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"no matching distribution found for\s+([a-zA-Z0-9_\-\.]+)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _looks_like_dependabot_transitive_conflict(text: str) -> bool:
    lowered = text.lower()
    return (
        "transitive_update_not_possible" in lowered
        or (
            "dependabot encountered" in lowered
            and "error performing the update" in lowered
        )
        or (
            "latest possible version that can be installed is" in lowered
            and "conflicting dependencies" in lowered
        )
    )


def _extract_dependabot_conflict_details(text: str) -> Dict[str, Any]:
    details: Dict[str, Any] = {}

    package_match = re.search(
        r"checking if\s+([a-zA-Z0-9_@./-]+)\s+([0-9][a-zA-Z0-9_.-]*)\s+needs updating",
        text,
        re.IGNORECASE,
    )
    if package_match:
        details["package"] = package_match.group(1)
        details["current_version"] = package_match.group(2)

    latest_match = re.search(
        r"latest version is\s+([0-9][a-zA-Z0-9_.-]*)",
        text,
        re.IGNORECASE,
    )
    if latest_match:
        details["latest_version"] = latest_match.group(1)

    blocker_pattern = re.compile(
        r"([a-zA-Z0-9_@./-]+)@([0-9][a-zA-Z0-9_.-]*)\s+requires\s+([a-zA-Z0-9_@./-]+)@([^\s]+)",
        re.IGNORECASE,
    )
    blockers: List[str] = []
    constraints: List[str] = []
    for match in blocker_pattern.finditer(text):
        blockers.append(match.group(1))
        constraints.append(f"{match.group(1)} requires {match.group(3)}@{match.group(4)}")
    if blockers:
        details["blockers"] = list(dict.fromkeys(blockers))[:4]
    if constraints:
        details["constraints"] = list(dict.fromkeys(constraints))[:4]

    return details

def choose_template(report: RCAReport, repo_context: Optional[RepoContext] = None) -> TemplateMatch:
    blob = "\n".join([l.text for l in report.key_lines[:200]])

    if report.failure_class == "environment_dependency_failure":
        if _looks_like_dependabot_transitive_conflict(blob):
            return TemplateMatch(
                "node_transitive_dependency_conflict",
                0.9,
                _extract_dependabot_conflict_details(blob),
            )
        mod = _extract_missing_module(blob)
        if mod:
            return TemplateMatch("python_add_dependency", 0.9, {"module": mod})
        pkg = _extract_no_matching_dist(blob)
        if pkg:
            return TemplateMatch("python_pin_dependency", 0.7, {"package": pkg})
        return TemplateMatch("python_env_general", 0.4, {})

    if report.failure_class == "workflow_configuration_error":
        return TemplateMatch("workflow_yaml_fix_hint", 0.5, {})

    if report.failure_class == "build_failure":
        has_node_build_context = bool(
            repo_context and (
                repo_context.package_scripts
                or any(path.endswith("package.json") for path in repo_context.manifests)
            )
        )
        if "tsc" in blob.lower() or has_node_build_context:
            return TemplateMatch("node_typescript_build_fix", 0.6, {})
        return TemplateMatch("build_general", 0.3, {})

    if report.failure_class == "test_failure":
        return TemplateMatch("test_reproduce_and_hint", 0.3, {})

    return TemplateMatch("unknown", 0.1, {})

def render_plan(
    report: RCAReport,
    tm: TemplateMatch,
    repo_context: Optional[RepoContext] = None,
) -> RemediationPlan:
    patches: List[Patch] = []
    cmds: List[str] = []
    assumptions: List[str] = []
    rollback: List[str] = []
    risk = "low"

    def _node_command(command: str, *packages: str) -> str:
        selected = [pkg for pkg in packages if pkg]
        if tm.fix_type == "node_transitive_dependency_conflict":
            package_manager = detect_primary_package_manager(repo_context) or "npm"
        else:
            package_manager = detect_primary_package_manager(repo_context) or "npm"
        if package_manager == "pnpm":
            if command == "outdated":
                return "pnpm outdated" + (f" {' '.join(selected)}" if selected else "")
            if command == "update_latest":
                return "pnpm up --latest" + (f" {' '.join(selected)}" if selected else "")
        if package_manager == "yarn":
            if command == "outdated":
                return "yarn outdated" + (f" {' '.join(selected)}" if selected else "")
            if command == "update_latest":
                return "yarn upgrade" + (f" {' '.join(f'{pkg}@latest' for pkg in selected)}" if selected else "")
        if command == "outdated":
            return "npm outdated" + (f" {' '.join(selected)}" if selected else "")
        if command == "update_latest":
            return "npm install" + (f" {' '.join(f'{pkg}@latest' for pkg in selected)}" if selected else "")
        raise ValueError(f"unsupported command kind: {command}")

    if tm.fix_type == "python_add_dependency":
        mod = tm.extracted["module"]
        cmds = [f"python -m pip install {mod}"]
        assumptions = [f"Python package name is '{mod}' (may differ from import name)."]
        manifest = primary_python_manifest(repo_context)
        if manifest:
            assumptions.append(f"Update dependency declaration in {manifest} so CI installs the package consistently.")
        elif repo_context is not None:
            assumptions.append("No Python dependency manifest was detected; create one or update the workflow install step explicitly.")
        workflow_path = preferred_workflow_path(repo_context)
        if workflow_path:
            assumptions.append(f"Verify the install step in {workflow_path} picks up the updated Python dependencies.")
        rollback = [f"python -m pip uninstall -y {mod}"]
        risk = "low"

    elif tm.fix_type == "python_pin_dependency":
        pkg = tm.extracted["package"]
        cmds = [f"python -m pip install '{pkg}==<PINNED_VERSION>'"]
        assumptions = [f"Need to choose a compatible version for {pkg} (pin)."]
        manifest = primary_python_manifest(repo_context)
        if manifest:
            assumptions.append(f"Persist the chosen version pin in {manifest}.")
        elif repo_context is not None:
            assumptions.append("No Python dependency manifest was detected; create one or update the workflow install step explicitly.")
        rollback = [f"python -m pip uninstall -y {pkg}"]
        risk = "medium"

    elif tm.fix_type == "node_typescript_build_fix":
        package_manager = detect_primary_package_manager(repo_context) or "npm"
        if package_manager == "pnpm":
            cmds = ["pnpm install --frozen-lockfile", "pnpm run build"]
        elif package_manager == "yarn":
            cmds = ["yarn install --frozen-lockfile", "yarn build"]
        else:
            cmds = ["npm ci", "npm run build"]
        assumptions = [f"Project uses {package_manager} and exposes a build script."]
        if repo_context and repo_context.package_scripts:
            manifest_paths = ", ".join(sorted(repo_context.package_scripts.keys())[:2])
            assumptions.append(f"Build scripts were detected in {manifest_paths}.")
        lockfiles = ", ".join(repo_context.lockfiles[:2]) if repo_context and repo_context.lockfiles else ""
        if lockfiles:
            rollback = [f"git checkout -- {lockfiles} || true"]
        else:
            rollback = ["git checkout -- package-lock.json yarn.lock pnpm-lock.yaml || true"]
        risk = "low"

    elif tm.fix_type == "workflow_yaml_fix_hint":
        cmds = []
        workflow_path = preferred_workflow_path(repo_context)
        if workflow_path:
            assumptions = [f"Workflow issue is likely in {workflow_path}."]
            rollback = [f"git checkout -- {workflow_path}"]
        else:
            assumptions = ["Workflow file path must be identified from error message."]
            rollback = ["git checkout -- .github/workflows/<file>.yml"]
        risk = "medium"

    elif tm.fix_type == "node_transitive_dependency_conflict":
        package = tm.extracted.get("package")
        blockers = [str(item) for item in tm.extracted.get("blockers", []) if str(item).strip()]
        constraints = [str(item) for item in tm.extracted.get("constraints", []) if str(item).strip()]
        if blockers:
            cmds = [
                _node_command("outdated", *blockers),
                _node_command("update_latest", *blockers),
            ]
        else:
            cmds = [
                _node_command("outdated"),
                _node_command("update_latest"),
            ]
        assumptions = []
        if package:
            assumptions.append(
                f"The blocked package is {package}; direct dependencies that constrain it must be updated before Dependabot can land the security fix."
            )
        else:
            assumptions.append(
                "A transitive dependency constraint is blocking Dependabot from applying the security update."
            )
        if constraints:
            assumptions.append("Observed constraint chain: " + "; ".join(constraints[:3]) + ".")
        assumptions.append("After updating the blocking direct dependencies, rerun the dependency update and confirm the vulnerable package can move to the fixed version.")
        rollback = ["git checkout -- package.json package-lock.json yarn.lock pnpm-lock.yaml || true"]
        risk = "medium"

    elif tm.fix_type == "test_reproduce_and_hint":
        cmds = []
        assumptions = ["Inspect the failing assertion or traceback before changing the implementation or expected fixture."]
        rollback = ["Revert the code or fixture changes if the targeted test still fails after the investigation."]
        risk = "low"

    else:
        cmds = []
        assumptions = ["Insufficient information for automated fix."]
        rollback = []
        risk = "high"

    return RemediationPlan(
        failure_class=report.failure_class,
        fix_type=tm.fix_type,
        patches=patches,
        commands=cmds,
        assumptions=assumptions,
        rollback=rollback,
        risk_level=risk,
        evidence={"template_score": tm.score, "extracted": tm.extracted, "repo_context_used": repo_context is not None},
    )
