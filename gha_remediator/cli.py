from __future__ import annotations

import argparse

from .cli_support.dispatch import dispatch_command
from .cli_support.evaluation_commands import add_evaluation_command_parsers
from .cli_support.export_commands import add_export_command_parsers
from .cli_support.runtime_commands import add_runtime_command_parsers
from .runtime_factory import build_remediator


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gha-remediator")
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    add_runtime_command_parsers(subparsers)
    add_evaluation_command_parsers(subparsers)
    add_export_command_parsers(subparsers)
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    dispatch_command(args, build_remediator_fn=build_remediator)


if __name__ == "__main__":
    main()
