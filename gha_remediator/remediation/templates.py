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

def choose_template(report: RCAReport, repo_context: Optional[RepoContext] = None) -> TemplateMatch:
    blob = "\n".join([l.text for l in report.key_lines[:200]])

    if report.failure_class == "environment_dependency_failure":
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
