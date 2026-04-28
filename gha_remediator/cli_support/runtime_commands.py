from __future__ import annotations

from .shared import add_model_args, add_preprocessing_mode_arg, add_verification_profile_arg


def add_runtime_command_parsers(subparsers) -> None:
    runp = subparsers.add_parser("run", help="Run RCA -> remediation -> verification on a log file")
    runp.add_argument("--log", required=True, help="Path to failed log file")
    runp.add_argument("--repo", default=None, help="Path to repo (optional; enables repo-aware planning and verification)")
    runp.add_argument("--success-logs-dir", default=None, help="Dir with recent successful logs (optional)")
    runp.add_argument("--replay", action="store_true", help="Attempt sandbox replay using act (if installed)")
    runp.add_argument("--job", default=None, help="Optional job name for act -j <job>")
    add_verification_profile_arg(
        runp,
        help_text="Verification policy profile to use when a repo is provided",
    )
    add_preprocessing_mode_arg(runp)
    runp.add_argument("--out", default=None, help="Write JSON output to file")
    add_model_args(runp)
    runp.add_argument("--synthetic-root", default="dataset/synthetic", help="Root directory for synthetic logs")
    runp.add_argument("--limit", type=int, default=None, help="Limit number of logs processed")
    runp.add_argument("--no-ground-truth", action="store_true", help="Ignore ground truth labels (if present)")

    inspectp = subparsers.add_parser("inspect-context", help="Inspect extracted repo context for a log/repo pair")
    inspectp.add_argument("--log", required=True, help="Path to failed log file")
    inspectp.add_argument("--repo", default=None, help="Optional path to repo to scan for context")
    inspectp.add_argument("--out", default=None, help="Write JSON output to file")

    debugp = subparsers.add_parser("debug-plan-input", help="Show the planner prompts and inputs for a log/repo pair")
    debugp.add_argument("--log", required=True, help="Path to failed log file")
    debugp.add_argument("--repo", default=None, help="Optional path to repo to scan for context")
    debugp.add_argument("--out", default=None, help="Write JSON output to file")
