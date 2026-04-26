from __future__ import annotations

import argparse
import csv
import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List

from gha_remediator.types import (
    LogBlock,
    LogLine,
    Patch,
    RCAReport,
    RemediationPlan,
    RepoCandidateFile,
    RepoContext,
    RepoSnippet,
)
from gha_remediator.verification import verify as verify_mod


def _repo_context_from_artifact(data: Dict[str, Any]) -> RepoContext | None:
    raw = (
        (data.get("remediation") or {}).get("evidence", {}).get("repo_context")
        or data.get("repo_context")
    )
    if not raw:
        return None
    return RepoContext(
        repo_root=raw.get("repo_root", ""),
        tree_entries=list(raw.get("tree_entries") or []),
        manifests=list(raw.get("manifests") or []),
        lockfiles=list(raw.get("lockfiles") or []),
        workflow_files=list(raw.get("workflow_files") or []),
        package_scripts=dict(raw.get("package_scripts") or {}),
        package_managers=dict(raw.get("package_managers") or {}),
        tool_versions=dict(raw.get("tool_versions") or {}),
        candidate_files=[
            RepoCandidateFile(
                path=item.get("path", ""),
                reason=item.get("reason", ""),
                line_hint=item.get("line_hint"),
            )
            for item in (raw.get("candidate_files") or [])
        ],
        snippets=[
            RepoSnippet(
                path=item.get("path", ""),
                reason=item.get("reason", ""),
                content=item.get("content", ""),
            )
            for item in (raw.get("snippets") or [])
        ],
        metadata=dict(raw.get("metadata") or {}),
    )


def _rca_report_from_artifact(data: Dict[str, Any]) -> RCAReport:
    pred = data.get("prediction") or {}
    key_lines = [
        LogLine(lineno=int(item.get("lineno", 0)), text=item.get("text", ""))
        for item in (pred.get("key_lines") or [])
    ]
    blocks = [
        LogBlock(
            start=int(item.get("start", 0)),
            end=int(item.get("end", 0)),
            lines=[],
            weight_density=float(item.get("weight_density", 0.0) or 0.0),
        )
        for item in (pred.get("blocks") or [])
    ]
    return RCAReport(
        failure_class=pred.get("failure_class", "unknown_failure"),
        key_lines=key_lines,
        blocks=blocks,
        root_causes=list(pred.get("root_causes") or []),
        root_cause_label=pred.get("root_cause_label"),
        root_cause_text=pred.get("root_cause_text"),
        confidence=pred.get("confidence"),
        evidence_line_numbers=list(pred.get("evidence_line_numbers") or []),
        notes=list(pred.get("notes") or []),
        metadata=dict(pred.get("metadata") or {}),
    )


def _plan_from_artifact(data: Dict[str, Any]) -> RemediationPlan:
    rem = data.get("remediation") or {}
    pred = data.get("prediction") or {}
    return RemediationPlan(
        failure_class=pred.get("failure_class", "unknown_failure"),
        fix_type=rem.get("fix_type", "unknown_fix"),
        patches=[
            Patch(path=item.get("path", ""), diff=item.get("diff", ""))
            for item in (rem.get("patches") or [])
        ],
        commands=list(rem.get("commands") or []),
        assumptions=list(rem.get("assumptions") or []),
        rollback=list(rem.get("rollback") or []),
        risk_level=rem.get("risk_level", "unknown"),
        evidence=dict(rem.get("evidence") or {}),
    )


@contextmanager
def _bypass_patch_apply() -> Iterator[None]:
    original = verify_mod.apply_plan_patches

    def fake_apply_plan_patches(workspace: Any, plan: RemediationPlan) -> Dict[str, Any]:
        return {
            "status": "passed",
            "reason": "patch apply gate bypassed for bottleneck analysis",
            "details": {
                "bypassed": True,
                "paths": [patch.path for patch in plan.patches],
                "mode": "diagnostic_skip_patch_apply",
                "patched_repo": str(getattr(workspace, "patched_repo", "")),
            },
        }

    verify_mod.apply_plan_patches = fake_apply_plan_patches
    try:
        yield
    finally:
        verify_mod.apply_plan_patches = original


def _iter_case_dirs(artifact_dirs: Iterable[Path]) -> Iterator[Path]:
    for artifact_dir in artifact_dirs:
        cases_dir = artifact_dir / "cases"
        for case_dir in sorted(cases_dir.iterdir()):
            if case_dir.is_dir():
                yield case_dir


def _collect_case_result(case_dir: Path) -> Dict[str, Any]:
    data = json.loads((case_dir / "result.json").read_text())
    plan = _plan_from_artifact(data)
    report = _rca_report_from_artifact(data)
    repo_context = _repo_context_from_artifact(data)
    repo_path = (data.get("status") or {}).get("repo_path")
    if not repo_path:
        raise RuntimeError(f"missing repo_path in {case_dir / 'result.json'}")

    original_verification = data.get("verification") or {}
    with _bypass_patch_apply():
        rerun = verify_mod.verify_plan(
            plan=plan,
            repo=repo_path,
            verification_profile=(data.get("run") or {}).get("verification_profile", "strict"),
            report=report,
            repo_context=repo_context,
        )

    gates = (rerun.evidence or {}).get("gates") or []
    terminal_gate = (rerun.evidence or {}).get("gate")
    return {
        "incident_id": data.get("incident_id"),
        "source_case_id": data.get("source_case_id"),
        "repo": ((data.get("remediation") or {}).get("evidence") or {}).get("repo_context", {}).get("repo_root", ""),
        "repo_path": repo_path,
        "original_status": original_verification.get("status"),
        "original_reason": original_verification.get("reason"),
        "bypass_status": rerun.status,
        "bypass_reason": rerun.reason,
        "terminal_gate": terminal_gate,
        "selected_validator": ((rerun.evidence or {}).get("capability") or {}).get("selected_validator"),
        "validator_summary": ((rerun.evidence or {}).get("capability") or {}).get("summary"),
        "num_patches": len(plan.patches),
        "num_commands": len(plan.commands),
        "gates": gates,
        "verification": asdict(rerun),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay verification on saved artifacts with patch_apply bypassed."
    )
    parser.add_argument(
        "--artifact-dir",
        action="append",
        required=True,
        help="Artifact directory containing a cases/ subtree. Pass multiple times to combine runs.",
    )
    parser.add_argument("--out-json", required=True, help="Path to output summary JSON.")
    parser.add_argument("--out-csv", required=True, help="Path to output case CSV.")
    args = parser.parse_args()

    artifact_dirs = [Path(p) for p in args.artifact_dir]
    rows: List[Dict[str, Any]] = []
    for case_dir in _iter_case_dirs(artifact_dirs):
        rows.append(_collect_case_result(case_dir))

    original_counts: Dict[str, int] = {}
    bypass_counts: Dict[str, int] = {}
    terminal_gate_counts: Dict[str, int] = {}
    transition_counts: Dict[str, int] = {}
    for row in rows:
        original_counts[row["original_status"]] = original_counts.get(row["original_status"], 0) + 1
        bypass_counts[row["bypass_status"]] = bypass_counts.get(row["bypass_status"], 0) + 1
        terminal_gate = row["terminal_gate"] or "unknown"
        terminal_gate_counts[terminal_gate] = terminal_gate_counts.get(terminal_gate, 0) + 1
        transition = f'{row["original_status"]} -> {row["bypass_status"]}'
        transition_counts[transition] = transition_counts.get(transition, 0) + 1

    out_json = Path(args.out_json)
    out_csv = Path(args.out_csv)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    summary = {
        "num_cases": len(rows),
        "artifact_dirs": [str(p) for p in artifact_dirs],
        "analysis": "verification replay with patch_apply bypassed; downstream gates run on workspace copy without applying the proposed patch",
        "original_status_counts": original_counts,
        "bypass_status_counts": bypass_counts,
        "terminal_gate_counts": terminal_gate_counts,
        "transition_counts": transition_counts,
        "cases": rows,
    }
    out_json.write_text(json.dumps(summary, indent=2))

    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "incident_id",
                "source_case_id",
                "original_status",
                "bypass_status",
                "terminal_gate",
                "selected_validator",
                "num_patches",
                "num_commands",
                "original_reason",
                "bypass_reason",
                "validator_summary",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "incident_id": row["incident_id"],
                    "source_case_id": row["source_case_id"],
                    "original_status": row["original_status"],
                    "bypass_status": row["bypass_status"],
                    "terminal_gate": row["terminal_gate"],
                    "selected_validator": row["selected_validator"],
                    "num_patches": row["num_patches"],
                    "num_commands": row["num_commands"],
                    "original_reason": row["original_reason"],
                    "bypass_reason": row["bypass_reason"],
                    "validator_summary": row["validator_summary"],
                }
            )

    print(json.dumps({k: summary[k] for k in [
        "num_cases",
        "original_status_counts",
        "bypass_status_counts",
        "terminal_gate_counts",
        "transition_counts",
    ]}, indent=2))
    print(f"Wrote JSON summary to {out_json}")
    print(f"Wrote case CSV to {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
