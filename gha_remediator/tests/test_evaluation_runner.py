import requests

from gha_remediator.evaluation.runner import (
    evaluate_synthetic_dataset,
    evidence_hit_ratio,
    expected_failure_class,
    load_evaluation_report,
)


class _StubRemediator:
    def __init__(self, result):
        self._result = result

    def run(self, raw_log_text, repo, replay=False, job=None):
        return self._result


def test_expected_failure_class_maps_known_type():
    gt = {"failure_type": "unit test failure"}
    assert expected_failure_class(gt) == "test_failure"


def test_expected_failure_class_returns_none_for_unknown():
    gt = {"failure_type": "totally unknown issue"}
    assert expected_failure_class(gt) is None


def test_evidence_hit_ratio_counts_matches():
    evidence = ["line A", "line B"]
    predicted = [{"text": "line A"}, {"text": "noise"}]
    assert evidence_hit_ratio(evidence, predicted) == 0.5


def test_evaluate_synthetic_dataset_summarises_case(monkeypatch, tmp_path):
    fake_logs = [
        {
            "path": str(tmp_path / "case.log"),
            "content": "fake log",
            "ground_truth": {
                "failure_type": "unit test failure",
                "evidence_lines": ["ReferenceError: someFunction is not defined"],
            },
        }
    ]
    fake_result = {
        "rca": {
            "failure_class": "test_failure",
            "key_lines": [{"text": "ReferenceError: someFunction is not defined"}],
        },
        "remediation": {
            "fix_type": "code_fix_hint",
            "risk_level": "low",
        },
        "verification": {
            "status": "inconclusive",
        },
    }

    monkeypatch.setattr(
        "gha_remediator.evaluation.runner.load_failure_logs",
        lambda root, limit, with_ground_truth: fake_logs,
    )

    report = evaluate_synthetic_dataset(
        remediator=_StubRemediator(fake_result),
        repo=str(tmp_path),
    )

    assert report["summary"]["num_cases"] == 1
    assert report["summary"]["classification_accuracy"] == 1.0
    assert report["summary"]["mean_evidence_hit_ratio"] == 1.0
    assert report["summary"]["verification_status_counts"] == {"inconclusive": 1}


def test_load_evaluation_report_returns_empty_for_missing(tmp_path):
    report = load_evaluation_report(str(tmp_path / "missing.json"))
    assert report == {"summary": {}, "cases": []}


def test_evaluate_synthetic_dataset_resumes_existing_case(monkeypatch, tmp_path):
    fake_logs = [
        {"path": str(tmp_path / "case1.log"), "content": "log1", "ground_truth": None},
        {"path": str(tmp_path / "case2.log"), "content": "log2", "ground_truth": None},
    ]
    fake_result = {
        "rca": {"failure_class": "unknown_failure", "key_lines": []},
        "remediation": {"fix_type": "llm_plan", "risk_level": "low"},
        "verification": {"status": "inconclusive"},
    }
    stub = _StubRemediator(fake_result)
    monkeypatch.setattr(
        "gha_remediator.evaluation.runner.load_failure_logs",
        lambda root, limit, with_ground_truth: fake_logs,
    )

    report = evaluate_synthetic_dataset(
        remediator=stub,
        repo=str(tmp_path),
        existing_report={
            "summary": {},
            "cases": [{"path": str(tmp_path / "case1.log"), "execution_status": "ok"}],
        },
    )

    assert len(report["cases"]) == 2
    assert stub._result == fake_result


def test_evaluate_synthetic_dataset_records_execution_errors(monkeypatch, tmp_path):
    fake_logs = [{"path": str(tmp_path / "case.log"), "content": "log", "ground_truth": None}]

    class _FailingRemediator:
        def run(self, raw_log_text, repo, replay=False, job=None):
            response = requests.Response()
            response.status_code = 429
            raise requests.HTTPError("Too Many Requests", response=response)

    monkeypatch.setattr(
        "gha_remediator.evaluation.runner.load_failure_logs",
        lambda root, limit, with_ground_truth: fake_logs,
    )
    monkeypatch.setattr("gha_remediator.evaluation.runner.time.sleep", lambda seconds: None)

    report = evaluate_synthetic_dataset(
        remediator=_FailingRemediator(),
        repo=str(tmp_path),
        max_retries=1,
    )

    assert report["summary"]["num_error_cases"] == 1
    assert report["summary"]["execution_status_counts"] == {"error": 1}
    assert report["cases"][0]["error_type"] == "HTTPError"
