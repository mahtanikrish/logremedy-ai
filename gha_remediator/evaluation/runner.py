from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from ..ingestion.synthetic_loader import load_failure_logs
from ..pipeline import GHARemediator
from ..types import FailureClass
from ..verification.policy import VerificationProfile


_FAILURE_TYPE_MAP = {
    "missing python module": "environment_dependency_failure",
    "missing node module": "environment_dependency_failure",
    "dependency install timeout": "environment_dependency_failure",
    "permission denied executing script": "infrastructure_failure",
    "docker permission denied": "infrastructure_failure",
    "unit test failure": "test_failure",
    "integration test timeout": "test_failure",
    "typescript build error": "build_failure",
    "java maven compilation error": "build_failure",
}


def expected_failure_class(ground_truth: Optional[Dict[str, Any]]) -> Optional[FailureClass]:
    if not ground_truth:
        return None
    failure_type = str(ground_truth.get("failure_type", "")).strip().lower()
    return _FAILURE_TYPE_MAP.get(failure_type)  # type: ignore[return-value]


def evidence_hit_ratio(evidence_lines: List[str], predicted_key_lines: List[Dict[str, Any]]) -> Optional[float]:
    if not evidence_lines:
        return None
    predicted_texts = [str(item.get("text", "")).strip() for item in predicted_key_lines]
    hits = 0
    for expected in evidence_lines:
        exp = expected.strip()
        if not exp:
            continue
        if any(exp in pred or pred in exp for pred in predicted_texts if pred):
            hits += 1
    return hits / max(1, len(evidence_lines))


def load_evaluation_report(path: str) -> Dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        return {"summary": {}, "cases": []}
    return json.loads(report_path.read_text(encoding="utf-8"))


def _run_case_with_retries(
    *,
    remediator: GHARemediator,
    raw_log_text: str,
    repo: Optional[str],
    replay: bool,
    max_retries: int,
    verification_profile: VerificationProfile,
) -> Dict[str, Any]:
    last_error: Optional[Exception] = None
    attempts = max(1, max_retries + 1)
    for attempt in range(attempts):
        try:
            return remediator.run(
                raw_log_text=raw_log_text,
                repo=repo,
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
    class_matches = 0
    class_total = 0
    evidence_scores: List[float] = []
    verification_counts: Counter[str] = Counter()
    execution_counts: Counter[str] = Counter()

    for case in cases:
        execution_counts[str(case.get("execution_status", "unknown"))] += 1
        if case.get("execution_status") != "ok":
            continue

        class_match = case.get("failure_class_match")
        if class_match is not None:
            class_total += 1
            class_matches += int(bool(class_match))

        evidence_score = case.get("evidence_hit_ratio")
        if isinstance(evidence_score, (int, float)):
            evidence_scores.append(float(evidence_score))

        verification_counts[str(case.get("verification_status"))] += 1

    return {
        "num_cases": len(cases),
        "num_completed_cases": execution_counts.get("ok", 0),
        "num_error_cases": len(cases) - execution_counts.get("ok", 0),
        "classification_accuracy": (class_matches / class_total) if class_total else None,
        "mean_evidence_hit_ratio": (sum(evidence_scores) / len(evidence_scores)) if evidence_scores else None,
        "verification_status_counts": dict(sorted(verification_counts.items())),
        "execution_status_counts": dict(sorted(execution_counts.items())),
    }


def evaluate_synthetic_dataset(
    *,
    remediator: GHARemediator,
    repo: Optional[str],
    root: str = "dataset/synthetic",
    limit: Optional[int] = None,
    replay: bool = False,
    sleep_seconds: float = 0.0,
    max_retries: int = 2,
    existing_report: Optional[Dict[str, Any]] = None,
    verification_profile: VerificationProfile = "strict",
) -> Dict[str, Any]:
    logs = load_failure_logs(root=root, limit=limit, with_ground_truth=True)
    prior_cases = list((existing_report or {}).get("cases", []))
    cases: List[Dict[str, Any]] = list(prior_cases)
    existing_by_path = {str(case.get("path")): case for case in prior_cases}

    for entry in logs:
        if entry["path"] in existing_by_path:
            continue

        ground_truth = entry.get("ground_truth")
        case: Dict[str, Any] = {
            "path": entry["path"],
            "ground_truth": ground_truth,
        }
        try:
            result = _run_case_with_retries(
                remediator=remediator,
                raw_log_text=entry["content"],
                repo=repo,
                replay=replay,
                max_retries=max_retries,
                verification_profile=verification_profile,
            )
            expected_class = expected_failure_class(ground_truth)
            predicted_class = result["rca"]["failure_class"]
            case.update(
                {
                    "execution_status": "ok",
                    "expected_failure_class": expected_class,
                    "predicted_failure_class": predicted_class,
                    "failure_class_match": expected_class == predicted_class if expected_class is not None else None,
                    "evidence_hit_ratio": evidence_hit_ratio(
                        list(ground_truth.get("evidence_lines", [])) if ground_truth else [],
                        list(result["rca"].get("key_lines", [])),
                    ),
                    "verification_status": result["verification"]["status"],
                    "fix_type": result["remediation"]["fix_type"],
                    "risk_level": result["remediation"]["risk_level"],
                    "result": result,
                }
            )
        except Exception as e:
            case.update(
                {
                    "execution_status": "error",
                    "error_type": type(e).__name__,
                    "error": str(e),
                }
            )
        cases.append(case)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return {"summary": _build_summary(cases), "cases": cases}


def write_evaluation_report(report: Dict[str, Any], out_path: str) -> None:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
