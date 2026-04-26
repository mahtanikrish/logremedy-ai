#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from gha_remediator.evaluation.lca_audit import (
    PARQUET_RELATIVE_PATHS,
    audit_dataset,
    resolve_dataset_root,
    write_audit_outputs,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit the LCA CI Builds Repair dataset for compatibility with the current remediation pipeline."
    )
    parser.add_argument(
        "--dataset-root",
        default=None,
        help="Path to the local Hugging Face LCA dataset checkout/download.",
    )
    parser.add_argument(
        "--config",
        choices=["default", "old", "both"],
        default="both",
        help="Dataset config to audit. 'old' is the larger 144-case superset, 'default' is the 68-case subset.",
    )
    parser.add_argument(
        "--out-dir",
        default="results/lca_audit",
        help="Directory to write JSON summary, JSONL case audit, and shortlist files.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=15,
        help="Number of top candidates to keep in the shortlist outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_root = resolve_dataset_root(args.dataset_root)
    configs = sorted(PARQUET_RELATIVE_PATHS) if args.config == "both" else [args.config]

    combined: dict[str, dict[str, str]] = {}
    for config in configs:
        report = audit_dataset(dataset_root, config=config, top_n=args.top_n)
        paths = write_audit_outputs(report, out_dir=args.out_dir)
        combined[config] = paths

    print(
        json.dumps(
            {
                "dataset_root": str(dataset_root),
                "configs": configs,
                "outputs": combined,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
