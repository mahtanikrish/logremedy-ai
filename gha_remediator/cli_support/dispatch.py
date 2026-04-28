from __future__ import annotations

import json
from pathlib import Path

from ..evaluation.benchmark_runner import (
    default_benchmark_artifact_dir,
    evaluate_benchmark_split,
    load_benchmark_report,
    write_benchmark_artifacts,
    write_benchmark_report,
    write_predictions_jsonl,
)
from ..evaluation.real_cases import export_real_case_stub
from ..evaluation.runner import evaluate_synthetic_dataset, load_evaluation_report, write_evaluation_report
from .payloads import (
    debug_plan_input_payload,
    inspect_context_payload,
    load_raw_log_text,
    write_or_print,
)


def dispatch_command(args, *, build_remediator_fn) -> None:
    if args.cmd == "export-real-case":
        paths = export_real_case_stub(
            repo=args.github_repo,
            run_id=args.run_id,
            out_dir=args.out_dir,
        )
        print(json.dumps(paths, indent=2))
        return

    if args.cmd == "inspect-context":
        payload = inspect_context_payload(
            load_raw_log_text(args),
            args.repo,
            build_remediator_fn=build_remediator_fn,
        )
        write_or_print(payload, args.out)
        return

    if args.cmd == "debug-plan-input":
        payload = debug_plan_input_payload(
            load_raw_log_text(args),
            args.repo,
            build_remediator_fn=build_remediator_fn,
        )
        write_or_print(payload, args.out)
        return

    remediator = build_remediator_fn(
        model=args.model,
        max_output_tokens=args.max_output_tokens,
        temperature=args.temperature,
        reasoning_effort=args.reasoning_effort,
    )

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
            verification_profile=args.verification_profile,
            preprocessing_mode=args.preprocessing_mode,
        )
        write_evaluation_report(report, args.out)
        print(json.dumps(report["summary"], indent=2))
        print(f"\nWrote detailed report to {args.out}")
        return

    if args.cmd == "eval-benchmark":
        artifact_dir = (
            Path(args.artifact_dir).expanduser().resolve()
            if args.artifact_dir
            else default_benchmark_artifact_dir(
                benchmark_root=args.benchmark_root,
                split=args.split,
                partition=args.partition,
                model=args.model,
                preprocessing_mode=args.preprocessing_mode,
            )
        )
        artifact_report_path = artifact_dir / "report.json"
        artifact_manifest_path = artifact_dir / "run_manifest.json"
        existing_report = None
        existing_manifest = None
        if args.resume:
            if artifact_report_path.exists():
                existing_report = load_benchmark_report(str(artifact_report_path))
            else:
                out_report_path = Path(args.out_report).expanduser()
                if out_report_path.exists():
                    existing_report = load_benchmark_report(str(out_report_path))
            if artifact_manifest_path.exists():
                with artifact_manifest_path.open("r", encoding="utf-8") as f:
                    existing_manifest = json.load(f)
        report = evaluate_benchmark_split(
            remediator=remediator,
            benchmark_root=args.benchmark_root,
            split=args.split,
            partition=args.partition,
            repo_base=args.repo_base,
            repo_map_path=args.repo_map,
            limit=args.limit,
            replay=args.replay,
            sleep_seconds=args.sleep_seconds,
            max_retries=args.max_retries,
            existing_report=existing_report,
            use_success_logs=not args.no_success_logs,
            artifact_root=str(artifact_dir),
            model_name=args.model,
            batch_size=args.batch_size,
            batch_number=args.batch_number,
            benchmark_mode=args.benchmark_mode,
            verification_profile=args.verification_profile,
            preprocessing_mode=args.preprocessing_mode,
        )
        write_benchmark_artifacts(
            artifact_root=artifact_dir,
            run_metadata={
                "artifact_version": 1,
                "run_name": artifact_dir.name,
                "artifact_root": str(artifact_dir),
                "benchmark_root": str(Path(args.benchmark_root).expanduser().resolve()),
                "split_path": str(
                    Path(args.split).expanduser().resolve()
                    if Path(args.split).expanduser().is_absolute()
                    else (Path(args.benchmark_root).expanduser().resolve() / args.split)
                ),
                "split_name": Path(args.split).stem,
                "partition": args.partition,
                "model": args.model,
                "batch_size": args.batch_size,
                "batch_number": args.batch_number,
                "benchmark_mode": report.get("benchmark_mode", args.benchmark_mode),
                "verification_profile": args.verification_profile,
                "preprocessing_mode": args.preprocessing_mode,
                "replay": args.replay,
                "use_success_logs": not args.no_success_logs,
                "max_retries": args.max_retries,
                "sleep_seconds": args.sleep_seconds,
                "created_at": (existing_manifest or {}).get("created_at"),
            },
            report=report,
        )
        write_benchmark_report(report, args.out_report)
        write_predictions_jsonl(report, args.out_predictions)
        print(json.dumps(report["summary"], indent=2))
        print(f"Benchmark mode: {report.get('benchmark_mode', args.benchmark_mode)}")
        if args.batch_size:
            batch_number = args.batch_number or 1
            print(f"Ran batch {batch_number} with batch size {args.batch_size}")
        print(f"\nWrote detailed report to {args.out_report}")
        print(f"Wrote scorer-ready predictions to {args.out_predictions}")
        print(f"Wrote reusable benchmark artifacts to {artifact_dir}")
        return

    raw_log_text = load_raw_log_text(args)
    result = remediator.run(
        raw_log_text,
        repo=args.repo,
        replay=args.replay,
        job=args.job,
        verification_profile=args.verification_profile,
        preprocessing_mode=args.preprocessing_mode,
    )
    write_or_print(result, args.out)
