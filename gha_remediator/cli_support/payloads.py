from __future__ import annotations

from dataclasses import asdict
import json

from .. import prompts
from ..ingestion.synthetic_loader import load_failure_logs
from ..remediation.llm_planner import build_planner_user_prompt
from ..repo_context import build_repo_context, format_repo_context


def load_raw_log_text(args) -> str:
    if args.log:
        with open(args.log, "r", encoding="utf-8") as f:
            return f.read()

    logs = load_failure_logs(
        root=args.synthetic_root,
        limit=1,
        with_ground_truth=not getattr(args, "no_ground_truth", False),
    )
    if not logs:
        raise RuntimeError("No synthetic logs found")
    return logs[0]["content"]


def write_or_print(payload: dict, out: str | None) -> None:
    js = json.dumps(payload, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(js)
        return
    print(js)


def inspect_context_payload(raw_log_text: str, repo: str | None, *, build_remediator_fn) -> dict:
    remediator = build_remediator_fn(enable_llm=False)
    report = remediator.analyze(raw_log_text)
    repo_context = build_repo_context(repo=repo, raw_log_text=raw_log_text, report=report)
    return {
        "failure_class": report.failure_class,
        "root_cause_label": report.root_cause_label,
        "root_cause_text": report.root_cause_text,
        "root_causes": report.root_causes,
        "confidence": report.confidence,
        "evidence_line_numbers": report.evidence_line_numbers,
        "notes": report.notes,
        "repo_context": asdict(repo_context),
        "repo_context_summary": format_repo_context(repo_context),
    }


def debug_plan_input_payload(raw_log_text: str, repo: str | None, *, build_remediator_fn) -> dict:
    remediator = build_remediator_fn(enable_llm=False)
    report = remediator.analyze(raw_log_text)
    docs = remediator.retrieve_knowledge(report, top_k=5)
    repo_context = build_repo_context(repo=repo, raw_log_text=raw_log_text, report=report)
    return {
        "failure_class": report.failure_class,
        "root_cause_label": report.root_cause_label,
        "root_cause_text": report.root_cause_text,
        "root_causes": report.root_causes,
        "confidence": report.confidence,
        "evidence_line_numbers": report.evidence_line_numbers,
        "notes": report.notes,
        "retrieved_docs": [{"id": d.doc_id, "title": d.title, "source": d.source} for d in docs],
        "repo_context": asdict(repo_context),
        "repo_context_summary": format_repo_context(repo_context),
        "system_prompt": prompts.PLAN_SYSTEM,
        "schema_hint": prompts.PLAN_SCHEMA_HINT,
        "user_prompt": build_planner_user_prompt(report, docs, repo_context),
    }
