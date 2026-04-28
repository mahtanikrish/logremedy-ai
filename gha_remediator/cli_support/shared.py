from __future__ import annotations


def add_model_args(parser) -> None:
    parser.add_argument("--model", default="gpt-4o-mini", help="Model name (default gpt-4o-mini)")
    parser.add_argument("--reasoning-effort", default=None, help="Optional reasoning effort (e.g. medium/high)")
    parser.add_argument("--temperature", type=float, default=None, help="Optional temperature")
    parser.add_argument("--max-output-tokens", type=int, default=1200, help="Max output tokens (default 1200)")


def add_verification_profile_arg(parser, *, help_text: str) -> None:
    parser.add_argument(
        "--verification-profile",
        choices=["strict", "benchmark_supported_files"],
        default="strict",
        help=help_text,
    )


def add_preprocessing_mode_arg(parser) -> None:
    parser.add_argument(
        "--preprocessing-mode",
        choices=["curated", "raw_tail"],
        default="curated",
        help="RCA input mode: curated uses filtering/expansion/pruning; raw_tail uses the raw log tail within budget",
    )
