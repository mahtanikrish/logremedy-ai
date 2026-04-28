from __future__ import annotations

from .shared import add_model_args, add_preprocessing_mode_arg, add_verification_profile_arg


def add_evaluation_command_parsers(subparsers) -> None:
    evalp = subparsers.add_parser("eval-synthetic", help="Run the full pipeline over the synthetic dataset")
    evalp.add_argument("--repo", default=None, help="Path to repo (optional; enables repo-aware planning and verification)")
    evalp.add_argument("--synthetic-root", default="dataset/synthetic", help="Root directory for synthetic logs")
    evalp.add_argument("--limit", type=int, default=None, help="Limit number of logs processed")
    evalp.add_argument("--replay", action="store_true", help="Attempt sandbox replay using act (if installed)")
    add_verification_profile_arg(
        evalp,
        help_text="Verification policy profile to use when a repo is provided",
    )
    add_preprocessing_mode_arg(evalp)
    evalp.add_argument("--out", default="results/synthetic_eval.json", help="Write evaluation report to file")
    add_model_args(evalp)
    evalp.add_argument("--sleep-seconds", type=float, default=0.0, help="Optional delay between cases")
    evalp.add_argument("--max-retries", type=int, default=2, help="Retries per case for transient LLM/API failures")
    evalp.add_argument("--resume", action="store_true", help="Resume from an existing evaluation report if present")

    benchmarkp = subparsers.add_parser(
        "eval-benchmark",
        help="Run the pipeline over a benchmark split and emit predictions for scoring",
    )
    benchmarkp.add_argument("--benchmark-root", required=True, help="Path to the benchmark repo root")
    benchmarkp.add_argument("--split", required=True, help="Split path relative to benchmark root or absolute path")
    benchmarkp.add_argument("--partition", choices=["train", "dev", "test", "all"], default="dev", help="Split partition to evaluate")
    benchmarkp.add_argument("--repo-base", default=None, help="Optional directory containing local repo checkouts keyed by metadata.repo")
    benchmarkp.add_argument("--repo-map", default=None, help="Optional JSON file mapping incident_id/source_case_id/repo to local repo paths")
    benchmarkp.add_argument("--artifact-dir", default=None, help="Optional benchmark artifact directory; defaults to benchmark_root/exports/evaluations/<split>__<partition>__<model>")
    benchmarkp.add_argument("--benchmark-mode", choices=["auto", "component", "full"], default="auto", help="Evaluation mode: auto selects component for component_real splits and full otherwise")
    benchmarkp.add_argument("--batch-size", type=int, default=None, help="Optional number of incidents to run per batch")
    benchmarkp.add_argument("--batch-number", type=int, default=None, help="1-based batch index to run when --batch-size is set")
    benchmarkp.add_argument("--limit", type=int, default=None, help="Optional limit on number of incidents")
    benchmarkp.add_argument("--replay", action="store_true", help="Attempt sandbox replay for each incident")
    add_verification_profile_arg(
        benchmarkp,
        help_text="Verification policy profile to use for full benchmark runs with repos",
    )
    benchmarkp.add_argument("--out-report", default="results/benchmark_eval.json", help="Write detailed benchmark report to file")
    benchmarkp.add_argument("--out-predictions", default="results/benchmark_predictions.jsonl", help="Write scorer-ready predictions JSONL to file")
    benchmarkp.add_argument("--sleep-seconds", type=float, default=0.0, help="Optional delay between incidents")
    benchmarkp.add_argument("--max-retries", type=int, default=2, help="Retries per incident for transient LLM/API failures")
    benchmarkp.add_argument("--resume", action="store_true", help="Resume from an existing benchmark report if present")
    benchmarkp.add_argument("--no-success-logs", action="store_true", help="Do not pass incident success_log.txt into preprocessing/RCA")
    add_preprocessing_mode_arg(benchmarkp)
    add_model_args(benchmarkp)
