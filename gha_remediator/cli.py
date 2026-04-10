from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from .evaluation.real_cases import export_real_case_stub
from .evaluation.runner import evaluate_synthetic_dataset, load_evaluation_report, write_evaluation_report
from .pipeline import GHARemediator
from .rag import KnowledgeBase, Doc
from .ingestion.synthetic_loader import load_failure_logs
from .llm.base import LLMConfig
from .llm.github_models_client import GitHubModelsClient
from .remediation.llm_planner import build_planner_user_prompt
from .repo_context import build_repo_context, format_repo_context
from . import prompts


def _default_kb() -> KnowledgeBase:
    docs = [
        Doc("py-missing-module", "Python: ModuleNotFoundError in CI",
            "If CI fails with ModuleNotFoundError, ensure the dependency is listed in requirements/pyproject and installed in the workflow. Prefer pinning known-good versions."),
        Doc("gha-yaml", "GitHub Actions: YAML workflow invalid",
            "Validate YAML syntax and check action inputs. Ensure uses: references exist and step keys are correctly indented."),
        Doc("node-build", "Node: build failed",
            "Run npm ci before build. Ensure correct node-version and that package-lock matches. Check tsc errors and tsconfig."),
    ]
    return KnowledgeBase(docs)

def _load_raw_log_text(args) -> str:
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

def _write_or_print(payload: dict, out: str | None) -> None:
    js = json.dumps(payload, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(js)
    else:
        print(js)

def _inspect_context_payload(raw_log_text: str, repo: str | None) -> dict:
    remediator = GHARemediator(kb=_default_kb())
    report = remediator.analyze(raw_log_text)
    repo_context = build_repo_context(repo=repo, raw_log_text=raw_log_text, report=report)
    return {
        "failure_class": report.failure_class,
        "root_causes": report.root_causes,
        "repo_context": asdict(repo_context),
        "repo_context_summary": format_repo_context(repo_context),
    }

def _debug_plan_input_payload(raw_log_text: str, repo: str | None) -> dict:
    remediator = GHARemediator(kb=_default_kb())
    report = remediator.analyze(raw_log_text)
    docs = remediator.retrieve_knowledge(report, top_k=5)
    repo_context = build_repo_context(repo=repo, raw_log_text=raw_log_text, report=report)
    return {
        "failure_class": report.failure_class,
        "root_causes": report.root_causes,
        "retrieved_docs": [{"id": d.doc_id, "title": d.title, "source": d.source} for d in docs],
        "repo_context": asdict(repo_context),
        "repo_context_summary": format_repo_context(repo_context),
        "system_prompt": prompts.PLAN_SYSTEM,
        "schema_hint": prompts.PLAN_SCHEMA_HINT,
        "user_prompt": build_planner_user_prompt(report, docs, repo_context),
    }

def main():
    ap = argparse.ArgumentParser(prog="gha-remediator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    runp = sub.add_parser("run", help="Run RCA -> remediation -> verification on a log file")
    runp.add_argument("--log", required=True, help="Path to failed log file")
    runp.add_argument("--repo", default=None, help="Path to repo (optional; enables repo-aware planning and verification)")
    runp.add_argument("--success-logs-dir", default=None, help="Dir with recent successful logs (optional)")
    runp.add_argument("--replay", action="store_true", help="Attempt sandbox replay using act (if installed)")
    runp.add_argument("--job", default=None, help="Optional job name for act -j <job>")
    runp.add_argument("--out", default=None, help="Write JSON output to file")

    runp.add_argument("--model", default="gpt-4o-mini", help="Model name (default gpt-4o-mini)")
    runp.add_argument("--reasoning-effort", default=None, help="Optional reasoning effort (e.g. medium/high)")
    runp.add_argument("--temperature", type=float, default=None, help="Optional temperature")
    runp.add_argument("--max-output-tokens", type=int, default=1200, help="Max output tokens (default 1200)")

    runp.add_argument("--synthetic-root", default="dataset/synthetic", help="Root directory for synthetic logs")
    runp.add_argument("--limit", type=int, default=None, help="Limit number of logs processed")
    runp.add_argument("--no-ground-truth", action="store_true", help="Ignore ground truth labels (if present)")

    evalp = sub.add_parser("eval-synthetic", help="Run the full pipeline over the synthetic dataset")
    evalp.add_argument("--repo", default=None, help="Path to repo (optional; enables repo-aware planning and verification)")
    evalp.add_argument("--synthetic-root", default="dataset/synthetic", help="Root directory for synthetic logs")
    evalp.add_argument("--limit", type=int, default=None, help="Limit number of logs processed")
    evalp.add_argument("--replay", action="store_true", help="Attempt sandbox replay using act (if installed)")
    evalp.add_argument("--out", default="results/synthetic_eval.json", help="Write evaluation report to file")
    evalp.add_argument("--model", default="gpt-4o-mini", help="Model name (default gpt-4o-mini)")
    evalp.add_argument("--reasoning-effort", default=None, help="Optional reasoning effort (e.g. medium/high)")
    evalp.add_argument("--temperature", type=float, default=None, help="Optional temperature")
    evalp.add_argument("--max-output-tokens", type=int, default=1200, help="Max output tokens (default 1200)")
    evalp.add_argument("--sleep-seconds", type=float, default=0.0, help="Optional delay between cases")
    evalp.add_argument("--max-retries", type=int, default=2, help="Retries per case for transient LLM/API failures")
    evalp.add_argument("--resume", action="store_true", help="Resume from an existing evaluation report if present")

    exportp = sub.add_parser("export-real-case", help="Export a real GitHub Actions run into an annotation stub")
    exportp.add_argument("--github-repo", required=True, help="GitHub repository in owner/name form")
    exportp.add_argument("--run-id", required=True, type=int, help="GitHub Actions run ID")
    exportp.add_argument("--out-dir", default="dataset/real_cases/cases", help="Directory for log and annotation files")
    exportp.add_argument("--model", default="gpt-4o-mini", help="Model name (default gpt-4o-mini)")
    exportp.add_argument("--reasoning-effort", default=None, help="Optional reasoning effort (e.g. medium/high)")
    exportp.add_argument("--temperature", type=float, default=None, help="Optional temperature")
    exportp.add_argument("--max-output-tokens", type=int, default=1200, help="Max output tokens (default 1200)")

    inspectp = sub.add_parser("inspect-context", help="Inspect extracted repo context for a log/repo pair")
    inspectp.add_argument("--log", required=True, help="Path to failed log file")
    inspectp.add_argument("--repo", default=None, help="Optional path to repo to scan for context")
    inspectp.add_argument("--out", default=None, help="Write JSON output to file")

    debugp = sub.add_parser("debug-plan-input", help="Show the planner prompts and inputs for a log/repo pair")
    debugp.add_argument("--log", required=True, help="Path to failed log file")
    debugp.add_argument("--repo", default=None, help="Optional path to repo to scan for context")
    debugp.add_argument("--out", default=None, help="Write JSON output to file")

    args = ap.parse_args()

    if args.cmd == "export-real-case":
        paths = export_real_case_stub(
            repo=args.github_repo,
            run_id=args.run_id,
            out_dir=args.out_dir,
        )
        print(json.dumps(paths, indent=2))
        return

    if args.cmd == "inspect-context":
        payload = _inspect_context_payload(_load_raw_log_text(args), args.repo)
        _write_or_print(payload, args.out)
        return

    if args.cmd == "debug-plan-input":
        payload = _debug_plan_input_payload(_load_raw_log_text(args), args.repo)
        _write_or_print(payload, args.out)
        return

    kb = _default_kb()
    llm = GitHubModelsClient()
    llm_cfg = LLMConfig(
        model=args.model,
        max_output_tokens=args.max_output_tokens,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
    )

    remediator = GHARemediator(kb=kb, llm=llm, llm_cfg=llm_cfg)

    if args.cmd == "eval-synthetic":
        existing_report = load_evaluation_report(args.out) if args.resume else None
        report = evaluate_synthetic_dataset(
            remediator=remediator,
            repo=args.repo,
            root=args.synthetic_root,
            limit=args.limit,
            replay=args.replay,
            sleep_seconds=args.sleep_seconds,
            max_retries=args.max_retries,
            existing_report=existing_report,
        )
        write_evaluation_report(report, args.out)
        print(json.dumps(report["summary"], indent=2))
        print(f"\nWrote detailed report to {args.out}")
        return

    raw_log_text = _load_raw_log_text(args)

    result = remediator.run(
        raw_log_text,
        repo=args.repo,
        replay=args.replay,
        job=args.job,
    )

    _write_or_print(result, args.out)

if __name__ == "__main__":
    main()
