from __future__ import annotations
from .types import FailureClass

def classify_failure(text: str) -> FailureClass:
    # Coarse rule-based failure classification
    msg = text.lower()

    if "transitive_update_not_possible" in msg:
        return "environment_dependency_failure"
    if "dependabot encountered" in msg and "error performing the update" in msg:
        return "environment_dependency_failure"
    if "latest possible version that can be installed is" in msg and "conflicting dependencies" in msg:
        return "environment_dependency_failure"

    if "no matching distribution found" in msg or "could not find a version that satisfies" in msg:
        return "environment_dependency_failure"
    if "modulenotfounderror" in msg or "no module named" in msg:
        return "environment_dependency_failure"

    if "test suite failed" in msg or "jest" in msg or "pytest" in msg:
        return "test_failure"
    if "referenceerror" in msg or "assertionerror" in msg:
        return "test_failure"

    if "tsc" in msg or "npm run build" in msg or "build failed" in msg:
        return "build_failure"

    if "workflow" in msg and ("invalid" in msg or "yaml" in msg):
        return "workflow_configuration_error"

    if "permission denied" in msg or "authentication" in msg or "unauthorized" in msg:
        return "infrastructure_failure"

    return "unknown_failure"
