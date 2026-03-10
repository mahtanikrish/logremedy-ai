from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import re

from ..types import RCAReport, RemediationPlan, Patch, FailureClass

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

def choose_template(report: RCAReport) -> TemplateMatch:
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
        if "tsc" in blob.lower():
            return TemplateMatch("node_typescript_build_fix", 0.6, {})
        return TemplateMatch("build_general", 0.3, {})

    if report.failure_class == "test_failure":
        return TemplateMatch("test_reproduce_and_hint", 0.3, {})

    return TemplateMatch("unknown", 0.1, {})

def render_plan(report: RCAReport, tm: TemplateMatch) -> RemediationPlan:
    patches: List[Patch] = []
    cmds: List[str] = []
    assumptions: List[str] = []
    rollback: List[str] = []
    risk = "low"

    if tm.fix_type == "python_add_dependency":
        mod = tm.extracted["module"]
        cmds = [f"python -m pip install {mod}"]
        assumptions = [f"Python package name is '{mod}' (may differ from import name)."]
        rollback = [f"python -m pip uninstall -y {mod}"]
        risk = "low"

    elif tm.fix_type == "python_pin_dependency":
        pkg = tm.extracted["package"]
        cmds = [f"python -m pip install '{pkg}==<PINNED_VERSION>'"]
        assumptions = [f"Need to choose a compatible version for {pkg} (pin)."]
        rollback = [f"python -m pip uninstall -y {pkg}"]
        risk = "medium"

    elif tm.fix_type == "node_typescript_build_fix":
        cmds = ["npm ci", "npm run build"]
        assumptions = ["Project uses npm and has a build script."]
        rollback = ["git checkout -- package-lock.json node_modules/ || true"]
        risk = "low"

    elif tm.fix_type == "workflow_yaml_fix_hint":
        cmds = []
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
        evidence={"template_score": tm.score, "extracted": tm.extracted},
    )
