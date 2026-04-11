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
    confidence: Optional[float] = None
    evidence_line_numbers: List[int] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class RepoCandidateFile:
    path: str
    reason: str
    line_hint: Optional[int] = None

@dataclass(frozen=True)
class RepoSnippet:
    path: str
    reason: str
    content: str

@dataclass
class RepoContext:
    repo_root: str
    tree_entries: List[str]
    manifests: List[str]
    lockfiles: List[str]
    workflow_files: List[str]
    package_scripts: Dict[str, Dict[str, str]] = field(default_factory=dict)
    package_managers: Dict[str, str] = field(default_factory=dict)
    tool_versions: Dict[str, List[str]] = field(default_factory=dict)
    candidate_files: List[RepoCandidateFile] = field(default_factory=list)
    snippets: List[RepoSnippet] = field(default_factory=list)
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
