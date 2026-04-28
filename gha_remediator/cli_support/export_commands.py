from __future__ import annotations

from .shared import add_model_args


def add_export_command_parsers(subparsers) -> None:
    exportp = subparsers.add_parser("export-real-case", help="Export a real GitHub Actions run into an annotation stub")
    exportp.add_argument("--github-repo", required=True, help="GitHub repository in owner/name form")
    exportp.add_argument("--run-id", required=True, type=int, help="GitHub Actions run ID")
    exportp.add_argument("--out-dir", default="dataset/real_cases/cases", help="Directory for log and annotation files")
    add_model_args(exportp)
