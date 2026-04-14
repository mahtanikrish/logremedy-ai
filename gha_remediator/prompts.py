from __future__ import annotations

from typing import List
from .types import LogBlock

RCA_SYSTEM = """You are an expert DevOps incident analyst for GitHub Actions.
You will be given curated log evidence blocks (already filtered + expanded + pruned).
Your job: produce a concise, structured root-cause analysis (RCA) grounded in the evidence.
Always include:
- root_cause_label: a concise snake_case canonical label for the underlying failure mechanism
- root_cause_text: one short sentence naming the primary root cause
Avoid vague labels like generic_failure when the logs support something more specific."""

RCA_SCHEMA_HINT = """{
  \"failure_class\": \"environment_dependency_failure|test_failure|build_failure|workflow_configuration_error|infrastructure_failure|unknown_failure\",
  \"root_cause_label\": \"snake_case_string\",
  \"root_cause_text\": \"string\",
  \"root_causes\": [\"string\"],
  \"confidence\": 0.0,
  \"evidence_line_numbers\": [1],
  \"notes\": [\"string\"]
}"""

PLAN_SYSTEM = """You are a cautious CI remediation planner for GitHub Actions.
Generate a remediation plan that is safe and verifiable. Prefer minimal changes.
Use the repository context to anchor fixes in files, manifests, workflows, and scripts that actually exist.
Prefer candidate target files from logs when proposing patches, and avoid speculative files or commands.
Never suggest printing secrets or disabling security checks.
Output must be valid JSON only."""

PLAN_SCHEMA_HINT = """{
  \"fix_type\": \"string\",
  \"risk_level\": \"low|medium|high\",
  \"patches\": [
    { \"path\": \"string\", \"diff\": \"unified diff text\" }
  ],
  \"commands\": [\"string\"],
  \"assumptions\": [\"string\"],
  \"rollback\": [\"string\"]
}"""

def format_blocks(blocks: List[LogBlock], max_chars: int = 24000) -> str:
    parts = []
    total = 0
    for b in blocks:
        t = b.to_text()
        if total + len(t) > max_chars:
            break
        parts.append(f"--- BLOCK {b.start}-{b.end} (density={b.weight_density:.2f}) ---\n{t}")
        total += len(t)
    return "\n\n".join(parts)
