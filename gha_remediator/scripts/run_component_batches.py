#!/usr/bin/env python3
"""Run component benchmark batches sequentially with optional token rotation.

This wrapper exists to make long component runs operationally safe:
- process a split in small batches
- optionally rotate GitHub tokens between batches
- keep a single artifact directory so results accumulate cleanly
- retry failed batches with a cooldown instead of forcing manual restarts

It is intentionally sequential. Parallel writes to the same artifact directory
are unsafe.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--partition", choices=["train", "dev", "test", "all"], default="dev")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--out-report", required=True)
    parser.add_argument("--out-predictions", required=True)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--preprocessing-mode", choices=["curated", "raw_tail"], default="curated")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--start-batch", type=int, default=1)
    parser.add_argument("--end-batch", type=int, default=None)
    parser.add_argument("--sleep-seconds", type=float, default=2.0, help="Delay passed to eval-benchmark between incidents")
    parser.add_argument("--cooldown-seconds", type=float, default=45.0, help="Delay between batches")
    parser.add_argument("--retry-cooldown-seconds", type=float, default=120.0, help="Delay before retrying a failed batch")
    parser.add_argument("--max-retries", type=int, default=2, help="Passed to eval-benchmark per incident")
    parser.add_argument("--batch-retries", type=int, default=2, help="Retries for an entire failed batch command")
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--no-success-logs", action="store_true")
    parser.add_argument("--tokens-file", default=None, help="Optional file with one GitHub token per line")
    parser.add_argument("--stop-on-error", action="store_true", help="Stop immediately if a batch keeps failing")
    return parser.parse_args()


def load_split_ids(split_path: Path, partition: str) -> list[str]:
    payload = json.loads(split_path.read_text(encoding="utf-8"))
    if partition == "all":
        return list(payload.get("train", [])) + list(payload.get("dev", [])) + list(payload.get("test", []))
    return list(payload.get(partition, []))


def load_tokens(path: str | None) -> list[str]:
    if not path:
        token = os.environ.get("GITHUB_TOKEN")
        return [token] if token else []

    token_lines = [
        line.strip()
        for line in Path(path).expanduser().read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return token_lines


def build_command(args: argparse.Namespace, batch_number: int) -> list[str]:
    cmd = [
        "python",
        "-m",
        "gha_remediator",
        "eval-benchmark",
        "--benchmark-root",
        args.benchmark_root,
        "--split",
        args.split,
        "--partition",
        args.partition,
        "--benchmark-mode",
        "component",
        "--model",
        args.model,
        "--preprocessing-mode",
        args.preprocessing_mode,
        "--artifact-dir",
        args.artifact_dir,
        "--batch-size",
        str(args.batch_size),
        "--batch-number",
        str(batch_number),
        "--resume",
        "--out-report",
        args.out_report,
        "--out-predictions",
        args.out_predictions,
        "--sleep-seconds",
        str(args.sleep_seconds),
        "--max-retries",
        str(args.max_retries),
        "--max-output-tokens",
        str(args.max_output_tokens),
    ]
    if args.reasoning_effort:
        cmd.extend(["--reasoning-effort", args.reasoning_effort])
    if args.temperature is not None:
        cmd.extend(["--temperature", str(args.temperature)])
    if args.no_success_logs:
        cmd.append("--no-success-logs")
    return cmd


def main() -> int:
    args = parse_args()

    benchmark_root = Path(args.benchmark_root).expanduser().resolve()
    split_path = Path(args.split).expanduser()
    if not split_path.is_absolute():
        split_path = (benchmark_root / split_path).resolve()

    artifact_dir = Path(args.artifact_dir).expanduser().resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    incident_ids = load_split_ids(split_path, args.partition)
    total_batches = max(1, math.ceil(len(incident_ids) / args.batch_size))
    end_batch = args.end_batch or total_batches
    if args.start_batch < 1 or end_batch < args.start_batch or end_batch > total_batches:
        raise SystemExit(
            f"Invalid batch range {args.start_batch}..{end_batch}; total batches for this split is {total_batches}."
        )

    tokens = load_tokens(args.tokens_file)
    if not tokens:
        raise SystemExit("No GitHub token available. Export GITHUB_TOKEN or provide --tokens-file.")

    print(
        json.dumps(
            {
                "split": str(split_path),
                "partition": args.partition,
                "num_incidents": len(incident_ids),
                "batch_size": args.batch_size,
                "start_batch": args.start_batch,
                "end_batch": end_batch,
                "total_batches": total_batches,
                "artifact_dir": str(artifact_dir),
                "preprocessing_mode": args.preprocessing_mode,
                "token_count": len(tokens),
            },
            indent=2,
        )
    )

    for batch_number in range(args.start_batch, end_batch + 1):
        token = tokens[(batch_number - args.start_batch) % len(tokens)]
        cmd = build_command(args, batch_number)

        print(f"\n=== Batch {batch_number}/{total_batches} ===")
        print(f"Using token slot {((batch_number - args.start_batch) % len(tokens)) + 1} of {len(tokens)}")
        print("Command:", " ".join(cmd))

        attempt = 0
        while True:
            attempt += 1
            env = dict(os.environ)
            env["GITHUB_TOKEN"] = token
            proc = subprocess.run(cmd, env=env)
            if proc.returncode == 0:
                break

            if attempt > args.batch_retries:
                print(f"Batch {batch_number} failed after {args.batch_retries} retries.")
                if args.stop_on_error:
                    return proc.returncode or 1
                break

            print(
                f"Batch {batch_number} failed with exit code {proc.returncode}. "
                f"Cooling down for {args.retry_cooldown_seconds} seconds before retry {attempt}/{args.batch_retries}."
            )
            time.sleep(args.retry_cooldown_seconds)

        if batch_number < end_batch:
            time.sleep(args.cooldown_seconds)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
