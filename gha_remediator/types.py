from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Literal


FailureClass = Literal[
    "environment_dependency_failure",
    "test_failure",
    "build_failure",
    "workflow_configuration_error",
    "infrastructure_failure",
    "unknown_failure",
]

VerificationStatus = Literal[
    "verified",
    "rejected_precondition",
    "rejected_policy",
    "rejected_static",
    "failed_replay",
    "inconclusive"
]


@dataclass(frozen=True)
class LogLine:
    lineno: int
    text: str

@dataclass(frozen=True)
class LogBlock:
    start: int
    end: int
    lines: List[LogLine]
    weight_density: float = 0.0

    def to_text(self) -> str:
        return "\n".join(f"{l.lineno}: {l.text}" for l in self.lines)

@dataclass
class RCAReport:
    failure_class: FailureClass
    key_lines: List[LogLine]
    blocks: List[LogBlock]
    root_causes: List[str]  # natural language
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Patch:
    path: str
    diff: str  # unified diff text

@dataclass
class RemediationPlan:
    failure_class: FailureClass
    fix_type: str
    patches: List[Patch]
    commands: List[str]
    assumptions: List[str]
    rollback: List[str]
    risk_level: str  # low/medium/high
    evidence: Dict[str, Any] = field(default_factory=dict)

@dataclass
class VerificationResult:
    status: VerificationStatus
    reason: str
    evidence: Dict[str, Any] = field(default_factory=dict)
