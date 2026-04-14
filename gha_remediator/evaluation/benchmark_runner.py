from __future__ import annotations

from dataclasses import asdict
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal

import requests

from ..pipeline import GHARemediator
from ..repo_context import build_repo_context
from ..types import RCAReport
from ..verification.policy import VerificationProfile


BenchmarkMode = Literal["auto", "component", "full"]

def _resolve_path(root: Path, maybe_relative: str | None) -> Path | None:
    if maybe_relative is None:
        return None
    candidate = Path(maybe_relative).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "run"


def default_benchmark_artifact_dir(*, benchmark_root: str, split: str, partition: str, model: str) -> Path:
    root = Path(benchmark_root).expanduser().resolve()
    split_name = Path(split).stem
    run_name = f"{_slugify(split_name)}__{_slugify(partition)}__{_slugify(model)}"
    return root / "exports" / "evaluations" / run_name


def _slice_cases_for_batch(
    cases: List[Dict[str, Any]],
    *,
    batch_size: Optional[int],
    batch_number: Optional[int],
) -> List[Dict[str, Any]]:
    if batch_size is None:
        if batch_number is not None:
            raise ValueError("--batch-number requires --batch-size")
        return cases

    if batch_size <= 0:
        raise ValueError("--batch-size must be greater than 0")

    number = batch_number or 1
    if number <= 0:
        raise ValueError("--batch-number must be greater than 0")

    start = (number - 1) * batch_size
    if start >= len(cases):
        raise ValueError(
            f"Requested batch {number} with batch size {batch_size}, "
            f"but only {len(cases)} case(s) are available."
        )
    return cases[start:start + batch_size]


def _enrich_case_result(case_result: Dict[str, Any], case_info: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(case_result)
    defaults = {
        "incident_id": case_info.get("incident_id"),
        "incident_dir": case_info.get("incident_dir"),
        "split_name": case_info.get("split_name"),
        "benchmark_group": case_info.get("benchmark_group"),
        "source_case_id": case_info.get("source_case_id"),
        "repo": case_info.get("repo"),
        "log_path": case_info.get("log_path"),
        "success_log_path": case_info.get("success_log_path"),
        "available_tasks": dict(case_info.get("metadata", {}).get("available_tasks", {})),
    }
    for key, value in defaults.items():
        if enriched.get(key) is None:
            enriched[key] = value
    return enriched


def _ordered_case_results(
    *,
    all_cases: List[Dict[str, Any]],
    accumulated_cases: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    ordered: List[Dict[str, Any]] = []
    for case_info in all_cases:
        incident_id = str(case_info.get("incident_id"))
        case_result = accumulated_cases.get(incident_id)
        if case_result is None:
            continue
        ordered.append(_enrich_case_result(case_result, case_info))
    return ordered


def _resolve_benchmark_mode(
    *,
    requested_mode: BenchmarkMode,
    cases: List[Dict[str, Any]],
) -> Literal["component", "full"]:
    if requested_mode != "auto":
        return requested_mode

    benchmark_groups = {
        str(case.get("benchmark_group"))
        for case in cases
        if case.get("benchmark_group") is not None
    }
    if benchmark_groups == {"component_real"}:
        return "component"
    return "full"


def load_benchmark_report(path: str) -> Dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        return {"summary": {}, "cases": []}
    return json.loads(report_path.read_text(encoding="utf-8"))


def write_benchmark_report(report: Dict[str, Any], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def write_predictions_jsonl(report: Dict[str, Any], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    for case in report.get("cases", []):
        if case.get("execution_status") != "ok":
            continue
        result = case.get("result")
        if not isinstance(result, dict):
            continue
        payload = dict(result)
        payload["incident_id"] = case.get("incident_id")
        payload["source_case_id"] = case.get("source_case_id")
        payload["benchmark_group"] = case.get("benchmark_group")
        payload["repo"] = case.get("repo")
        lines.append(json.dumps(payload, sort_keys=True))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _serialize_rca_report(report: RCAReport) -> Dict[str, Any]:
    return {
        "failure_class": report.failure_class,
        "root_cause_label": report.root_cause_label,
        "root_cause_text": report.root_cause_text,
        "root_causes": report.root_causes,
        "confidence": report.confidence,
        "evidence_line_numbers": report.evidence_line_numbers,
        "notes": report.notes,
    }


def _serialize_repo_context_summary(repo_context: Any) -> Dict[str, Any]:
    return {
        "repo_root": repo_context.repo_root,
        "manifests": list(repo_context.manifests),
        "lockfiles": list(repo_context.lockfiles),
        "workflow_files": list(repo_context.workflow_files),
        "candidate_files": [asdict(item) for item in repo_context.candidate_files],
        "metadata": dict(repo_context.metadata),
    }


def _case_result_summary(case_result: Dict[str, Any]) -> Dict[str, Any]:
    if case_result.get("execution_status") != "ok":
        return {
            "execution_status": case_result.get("execution_status"),
            "error_type": case_result.get("error_type"),
            "error": case_result.get("error"),
        }

    result = case_result.get("result", {})
    rca = result.get("rca", {}) if isinstance(result, dict) else {}
    verification = result.get("verification", {}) if isinstance(result, dict) else {}
    evidence_lines = rca.get("evidence_line_numbers") if isinstance(rca, dict) else []
    return {
        "execution_status": "ok",
        "benchmark_mode": case_result.get("benchmark_mode"),
        "predicted_failure_class": rca.get("failure_class"),
        "predicted_root_cause_label": rca.get("root_cause_label"),
        "predicted_root_cause_text": rca.get("root_cause_text"),
        "num_root_causes": len(rca.get("root_causes", [])) if isinstance(rca.get("root_causes"), list) else 0,
        "num_evidence_lines": len(evidence_lines) if isinstance(evidence_lines, list) else 0,
        "verification_status": verification.get("status"),
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_case_result_artifact(
    *,
    artifact_root: Path,
    run_metadata: Dict[str, Any],
    case_result: Dict[str, Any],
) -> None:
    case_dir = artifact_root / "cases" / str(case_result["incident_id"])
    result_payload = case_result.get("result", {}) if isinstance(case_result.get("result"), dict) else {}
    payload = {
        "artifact_version": 1,
        "run": {
            "run_name": run_metadata.get("run_name"),
            "artifact_root": run_metadata.get("artifact_root"),
            "split_name": run_metadata.get("split_name"),
            "split_path": run_metadata.get("split_path"),
            "partition": run_metadata.get("partition"),
            "model": run_metadata.get("model"),
            "batch_size": run_metadata.get("batch_size"),
            "batch_number": run_metadata.get("batch_number"),
            "benchmark_mode": run_metadata.get("benchmark_mode"),
            "verification_profile": run_metadata.get("verification_profile"),
        },
        "incident_id": case_result.get("incident_id"),
        "source_case_id": case_result.get("source_case_id"),
        "benchmark_group": case_result.get("benchmark_group"),
        "available_tasks": case_result.get("available_tasks"),
        "completed_at": _utc_now(),
        "status": {
            "execution_status": case_result.get("execution_status"),
            "repo_resolution": case_result.get("repo_resolution"),
            "repo_path": case_result.get("repo_path"),
            "verification_status": case_result.get("verification_status"),
        },
        "paths": {
            "incident_dir": case_result.get("incident_dir"),
            "log_path": case_result.get("log_path"),
            "success_log_path": case_result.get("success_log_path"),
        },
        "result_summary": _case_result_summary(case_result),
        "prediction": result_payload.get("rca"),
        "repo_context": result_payload.get("repo_context"),
    }
    if case_result.get("execution_status") != "ok":
        payload["error"] = {
            "type": case_result.get("error_type"),
            "message": case_result.get("error"),
        }
    elif run_metadata.get("benchmark_mode") == "full":
        payload["remediation"] = result_payload.get("remediation")
        payload["verification"] = result_payload.get("verification")
    _write_json(case_dir / "result.json", payload)


def write_benchmark_artifacts(
    *,
    artifact_root: Path,
    run_metadata: Dict[str, Any],
    report: Dict[str, Any],
) -> None:
    artifact_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        **run_metadata,
        "updated_at": _utc_now(),
        "summary": report.get("summary", {}),
        "num_cases_materialized": len(report.get("cases", [])),
    }
    _write_json(artifact_root / "run_manifest.json", manifest)
    write_benchmark_report(report, str(artifact_root / "report.json"))
    write_predictions_jsonl(report, str(artifact_root / "predictions.jsonl"))
    for case in report.get("cases", []):
        if isinstance(case, dict) and case.get("incident_id"):
            write_case_result_artifact(
                artifact_root=artifact_root,
                run_metadata=run_metadata,
                case_result=case,
            )


def _load_repo_map(path: str | None) -> Dict[str, str]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("repo map must be a JSON object of key -> local path")
    normalized: Dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, str):
            normalized[key] = value
    return normalized


def _resolve_repo_path(
    *,
    incident_id: str,
    source_case_id: str | None,
    repo_name: str,
    repo_base: str | None,
    repo_map: Dict[str, str],
) -> tuple[Optional[str], str]:
    for key in (incident_id, source_case_id, repo_name):
        if key and key in repo_map:
            candidate = Path(repo_map[key]).expanduser().resolve()
            if candidate.exists() and candidate.is_dir():
                return str(candidate), "mapped"
            return None, "mapped_missing"

    if repo_base:
        candidate = Path(repo_base).expanduser().resolve() / repo_name
        if candidate.exists() and candidate.is_dir():
            return str(candidate), "repo_base"
        return None, "repo_base_missing"

    return None, "not_provided"


def load_benchmark_cases(
    *,
    benchmark_root: str,
    split: str,
    partition: str = "dev",
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    root = Path(benchmark_root).expanduser().resolve()
    split_path = _resolve_path(root, split)
    if split_path is None or not split_path.exists():
        raise FileNotFoundError(f"Split file not found: {split}")

    split_payload = json.loads(split_path.read_text(encoding="utf-8"))
    if partition == "all":
        incident_ids = list(split_payload.get("train", [])) + list(split_payload.get("dev", [])) + list(split_payload.get("test", []))
    else:
        incident_ids = list(split_payload.get(partition, []))

    if limit is not None:
        incident_ids = incident_ids[:limit]

    cases: List[Dict[str, Any]] = []
    for incident_id in incident_ids:
        incident_dir = root / "incidents" / incident_id
        metadata = json.loads((incident_dir / "metadata.json").read_text(encoding="utf-8"))
        labels = json.loads((incident_dir / "labels.json").read_text(encoding="utf-8"))
        log_path = incident_dir / "failing_log.txt"
        success_log_path = incident_dir / "success_log.txt"
        cases.append(
            {
                "incident_id": incident_id,
                "incident_dir": str(incident_dir),
                "split_name": split_payload.get("name"),
                "benchmark_group": metadata.get("benchmark_group"),
                "source_case_id": metadata.get("source_case_id"),
                "repo": metadata.get("repo"),
                "metadata": metadata,
                "labels": labels,
                "log_path": str(log_path),
                "success_log_path": str(success_log_path) if success_log_path.exists() else None,
            }
        )
    return cases


def _run_case_with_retries(
    *,
    remediator: GHARemediator,
    raw_log_text: str,
    repo: Optional[str],
    success_logs: Optional[List[str]],
    replay: bool,
    max_retries: int,
    benchmark_mode: Literal["component", "full"],
    verification_profile: VerificationProfile,
) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    attempts = max(1, max_retries + 1)
    for attempt in range(attempts):
        try:
            if benchmark_mode == "component":
                report = remediator.analyze(raw_log_text, success_logs=success_logs)
                result: Dict[str, Any] = {
                    "rca": _serialize_rca_report(report),
                }
                if repo is not None and str(repo).strip():
                    repo_context = build_repo_context(repo=repo, raw_log_text=raw_log_text, report=report)
                    result["repo_context"] = _serialize_repo_context_summary(repo_context)
                return result
            return remediator.run(
                raw_log_text=raw_log_text,
                repo=repo,
                success_logs=success_logs,
                replay=replay,
                job=None,
                verification_profile=verification_profile,
            )
        except requests.HTTPError as e:
            last_error = e
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code != 429 or attempt == attempts - 1:
                raise
            retry_after = getattr(getattr(e, "response", None), "headers", {}).get("Retry-After")
            if retry_after is not None:
                try:
                    delay_seconds = float(retry_after)
                except ValueError:
                    delay_seconds = 0.0
            else:
                delay_seconds = min(60.0, 5.0 * (2 ** attempt))
            time.sleep(delay_seconds)
        except Exception as e:
            last_error = e
            if attempt == attempts - 1:
                raise
            time.sleep(min(10, 2 ** attempt))
    if last_error is not None:
        raise last_error
    raise RuntimeError("Case execution failed without an exception.")


def _build_summary(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    execution_counts: Counter[str] = Counter()
    verification_counts: Counter[str] = Counter()
    repo_resolution_counts: Counter[str] = Counter()
    benchmark_modes: Counter[str] = Counter()

    for case in cases:
        execution_counts[str(case.get("execution_status", "unknown"))] += 1
        repo_resolution_counts[str(case.get("repo_resolution", "unknown"))] += 1
        benchmark_modes[str(case.get("benchmark_mode", "unknown"))] += 1
        if case.get("execution_status") == "ok" and case.get("verification_status") is not None:
            verification_counts[str(case.get("verification_status", "unknown"))] += 1

    return {
        "num_cases": len(cases),
        "num_completed_cases": execution_counts.get("ok", 0),
        "num_error_cases": len(cases) - execution_counts.get("ok", 0),
        "benchmark_mode_counts": dict(sorted(benchmark_modes.items())),
        "execution_status_counts": dict(sorted(execution_counts.items())),
        "verification_status_counts": dict(sorted(verification_counts.items())),
        "repo_resolution_counts": dict(sorted(repo_resolution_counts.items())),
    }


def evaluate_benchmark_split(
    *,
    remediator: GHARemediator,
    benchmark_root: str,
    split: str,
    partition: str = "dev",
    repo_base: Optional[str] = None,
    repo_map_path: Optional[str] = None,
    limit: Optional[int] = None,
    replay: bool = False,
    sleep_seconds: float = 0.0,
    max_retries: int = 2,
    existing_report: Optional[Dict[str, Any]] = None,
    use_success_logs: bool = True,
    artifact_root: Optional[str] = None,
    model_name: Optional[str] = None,
    batch_size: Optional[int] = None,
    batch_number: Optional[int] = None,
    benchmark_mode: BenchmarkMode = "auto",
    verification_profile: VerificationProfile = "strict",
) -> Dict[str, Any]:
    all_cases = load_benchmark_cases(
        benchmark_root=benchmark_root,
        split=split,
        partition=partition,
        limit=limit,
    )
    resolved_benchmark_mode = _resolve_benchmark_mode(
        requested_mode=benchmark_mode,
        cases=all_cases,
    )
    cases_to_run = _slice_cases_for_batch(
        all_cases,
        batch_size=batch_size,
        batch_number=batch_number,
    )
    repo_map = _load_repo_map(repo_map_path)
    prior_cases = {
        str(case.get("incident_id")): case
        for case in list((existing_report or {}).get("cases", []))
        if isinstance(case, dict) and case.get("incident_id")
    }
    case_info_by_id = {
        str(case_info["incident_id"]): case_info
        for case_info in all_cases
    }
    accumulated_cases = {
        incident_id: _enrich_case_result(case_result, case_info_by_id[incident_id])
        for incident_id, case_result in prior_cases.items()
        if incident_id in case_info_by_id
    }

    for case_info in cases_to_run:
        incident_id = case_info["incident_id"]
        existing_case = prior_cases.get(incident_id)
        if existing_case is not None and existing_case.get("execution_status") == "ok":
            accumulated_cases[incident_id] = _enrich_case_result(existing_case, case_info)
            continue

        repo_path, repo_resolution = _resolve_repo_path(
            incident_id=incident_id,
            source_case_id=case_info.get("source_case_id"),
            repo_name=str(case_info.get("repo", "")),
            repo_base=repo_base,
            repo_map=repo_map,
        )
        log_text = Path(case_info["log_path"]).read_text(encoding="utf-8", errors="replace")
        success_logs: Optional[List[str]] = None
        if use_success_logs and case_info.get("success_log_path"):
            success_logs = [
                Path(case_info["success_log_path"]).read_text(encoding="utf-8", errors="replace")
            ]

        case_result: Dict[str, Any] = {
            "incident_id": incident_id,
            "incident_dir": case_info.get("incident_dir"),
            "split_name": case_info.get("split_name"),
            "benchmark_group": case_info.get("benchmark_group"),
            "source_case_id": case_info.get("source_case_id"),
            "repo": case_info.get("repo"),
            "repo_path": repo_path,
            "repo_resolution": repo_resolution,
            "benchmark_mode": resolved_benchmark_mode,
            "log_path": case_info.get("log_path"),
            "success_log_path": case_info.get("success_log_path"),
            "available_tasks": dict(case_info.get("metadata", {}).get("available_tasks", {})),
        }

        try:
            result = _run_case_with_retries(
                remediator=remediator,
                raw_log_text=log_text,
                repo=repo_path,
                success_logs=success_logs,
                replay=replay,
                max_retries=max_retries,
                benchmark_mode=resolved_benchmark_mode,
                verification_profile=verification_profile,
            )
            case_result.update(
                {
                    "execution_status": "ok",
                    "verification_status": result.get("verification", {}).get("status"),
                    "result": result,
                }
            )
        except Exception as e:
            case_result.update(
                {
                    "execution_status": "error",
                    "error_type": type(e).__name__,
                    "error": str(e),
                }
            )

        accumulated_cases[incident_id] = case_result
        if artifact_root:
            ordered_cases = _ordered_case_results(
                all_cases=all_cases,
                accumulated_cases=accumulated_cases,
            )
            current_report = {
                "summary": _build_summary(ordered_cases),
                "cases": ordered_cases,
            }
            artifact_path = Path(artifact_root).expanduser().resolve()
            write_benchmark_artifacts(
                artifact_root=artifact_path,
                run_metadata={
                    "artifact_version": 1,
                    "run_name": artifact_path.name,
                    "artifact_root": str(artifact_path),
                    "benchmark_root": str(Path(benchmark_root).expanduser().resolve()),
                    "split_path": str(_resolve_path(Path(benchmark_root).expanduser().resolve(), split)),
                    "split_name": case_info.get("split_name"),
                    "partition": partition,
                    "model": model_name,
                    "batch_size": batch_size,
                    "batch_number": batch_number,
                    "benchmark_mode": resolved_benchmark_mode,
                    "verification_profile": verification_profile,
                    "replay": replay,
                    "use_success_logs": use_success_logs,
                    "max_retries": max_retries,
                    "sleep_seconds": sleep_seconds,
                    "created_at": _utc_now(),
                },
                report=current_report,
            )
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    ordered_cases = _ordered_case_results(
        all_cases=all_cases,
        accumulated_cases=accumulated_cases,
    )
    return {
        "benchmark_mode": resolved_benchmark_mode,
        "summary": _build_summary(ordered_cases),
        "cases": ordered_cases,
    }
