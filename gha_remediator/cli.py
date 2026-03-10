from __future__ import annotations

import argparse
import json

from .pipeline import GHARemediator
from .rag import KnowledgeBase, Doc
from .ingestion.synthetic_loader import load_failure_logs
from .llm.base import LLMConfig
from .llm.github_models_client import GitHubModelsClient


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

def main():
    ap = argparse.ArgumentParser(prog="gha-remediator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    runp = sub.add_parser("run", help="Run RCA -> remediation -> verification on a log file")
    runp.add_argument("--log", required=True, help="Path to failed log file")
    runp.add_argument("--repo", required=True, help="Path to repo (for verification checks)")
    runp.add_argument("--success-logs-dir", default=None, help="Dir with recent successful logs (optional)")
    runp.add_argument("--replay", action="store_true", help="Attempt sandbox replay using act (if installed)")
    runp.add_argument("--job", default=None, help="Optional job name for act -j <job>")
    runp.add_argument("--out", default=None, help="Write JSON output to file")

    runp.add_argument("--llm", action="store_true", help="Enable LLM for RCA + planning (OpenAI Responses API)")
    runp.add_argument("--model", default="gpt-5.2", help="Model name (default gpt-5.2)")
    runp.add_argument("--reasoning-effort", default=None, help="Optional reasoning effort (e.g. medium/high)")
    runp.add_argument("--temperature", type=float, default=None, help="Optional temperature")
    runp.add_argument("--max-output-tokens", type=int, default=1200, help="Max output tokens (default 1200)")

    runp.add_argument("--synthetic-root", default="dataset/synthetic", help="Root directory for synthetic logs")
    runp.add_argument("--limit", type=int, default=None, help="Limit number of logs processed")
    runp.add_argument("--no-ground-truth", action="store_true", help="Ignore ground truth labels (if present)")

    args = ap.parse_args()
    
    kb = _default_kb()

    llm = None
    llm_cfg = None

    if args.llm:
        llm = GitHubModelsClient()
        llm_cfg = LLMConfig(
            model=args.model,
            max_output_tokens=args.max_output_tokens,
            temperature=args.temperature,
        )


    remediator = GHARemediator(kb=kb, llm=llm, llm_cfg=llm_cfg)

    if args.log:
        with open(args.log, "r", encoding="utf-8") as f:
            raw_log_text = f.read()
    else:
        logs = load_failure_logs(
            root=args.synthetic_root,
            limit=1,
            with_ground_truth=not args.no_ground_truth,
        )
        if not logs:
            raise RuntimeError("No synthetic logs found")
        raw_log_text = logs[0]["content"]

    result = remediator.run(
        raw_log_text,
        repo=args.repo,
        replay=args.replay,
        job=args.job,
    )


    js = json.dumps(result, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(js)
    else:
        print(js)

if __name__ == "__main__":
    main()
