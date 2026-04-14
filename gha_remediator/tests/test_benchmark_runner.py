import json

from gha_remediator.evaluation.benchmark_runner import (
    default_benchmark_artifact_dir,
    evaluate_benchmark_split,
    load_benchmark_cases,
    load_benchmark_report,
    write_benchmark_artifacts,
    write_benchmark_report,
    write_predictions_jsonl,
)
from gha_remediator.types import RCAReport


class _StubRemediator:
    def __init__(self):
        self.calls = []

    def analyze(self, raw_log_text, success_logs=None):
        self.calls.append(
            {
                "method": "analyze",
                "raw_log_text": raw_log_text,
                "success_logs": success_logs,
            }
        )
        return RCAReport(
            failure_class="build_failure",
            key_lines=[],
            blocks=[],
            root_causes=["synthetic root cause"],
            root_cause_label="synthetic_root_cause",
            root_cause_text="synthetic root cause",
            confidence=0.9,
            evidence_line_numbers=[2],
            notes=[],
            metadata={},
        )

    def run(
        self,
        raw_log_text,
        repo,
        success_logs=None,
        replay=False,
        job=None,
        verification_profile="strict",
    ):
        self.calls.append(
            {
                "method": "run",
                "raw_log_text": raw_log_text,
                "repo": repo,
                "success_logs": success_logs,
                "replay": replay,
                "job": job,
                "verification_profile": verification_profile,
            }
        )
        return {
            "rca": {
                "failure_class": "build_failure",
                "root_cause_label": "synthetic_root_cause",
                "root_cause_text": "synthetic root cause",
                "root_causes": ["synthetic root cause"],
                "confidence": 0.9,
                "evidence_line_numbers": [2],
                "notes": [],
                "metadata": {},
                "key_lines": [],
                "blocks": [],
            },
            "remediation": {
                "fix_type": "template_fix",
                "risk_level": "low",
                "commands": [],
                "assumptions": [],
                "rollback": [],
                "patches": [],
                "evidence": {},
            },
            "verification": {
                "status": "inconclusive",
                "reason": "no repo",
                "evidence": {},
            },
        }


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_benchmark_root(tmp_path):
    benchmark_root = tmp_path / "benchmark"

    incident_a = benchmark_root / "incidents" / "INC2001"
    incident_b = benchmark_root / "incidents" / "INC2002"

    metadata_a = {
        "incident_id": "INC2001",
        "benchmark_group": "component_real",
        "source": "logsage_experiment_dataset",
        "source_case_id": "logsage:demo/pair_1",
        "repo": "demo-repo",
        "ecosystem": "python",
        "reproducible": False,
        "available_tasks": {
            "preprocessing": True,
            "classification": True,
            "evidence_extraction": True,
            "rca": True,
            "repo_context_reasoning": False,
            "fix_intent": False,
            "verification": False,
            "e2e": False,
        },
        "log_stats": {"total_lines": 3, "error_line_count": 1},
    }
    labels_a = {
        "incident_id": "INC2001",
        "failure_class": "build_failure",
        "root_cause_label": "demo",
        "root_cause_text": "demo root cause",
        "evidence_lines": None,
        "evidence_spans": [{"start": 2, "end": 2, "type": "abnormal_segment"}],
        "repo_context_needed": None,
        "repo_context_types": [],
        "fix_intent": None,
        "target_files": None,
        "acceptable_commands": [],
        "acceptable_patch_paths": [],
        "safety_expected": None,
        "expected_verification": None,
        "failure_properties": None,
        "ambiguity": "low",
        "exclude_from_primary": False,
        "exclusion_reason": None,
        "annotator": "test",
        "reviewer": None,
        "status": "reviewed",
        "notes": [],
    }

    metadata_b = {
        **metadata_a,
        "incident_id": "INC2002",
        "source_case_id": "logsage:demo/pair_2",
        "repo": "other-repo",
    }
    labels_b = {**labels_a, "incident_id": "INC2002"}

    _write(incident_a / "metadata.json", metadata_a)
    _write(incident_a / "labels.json", labels_a)
    _write(incident_a / "failing_log.txt", "line 1\nERROR line\nline 3\n")
    _write(incident_a / "success_log.txt", "success 1\nsuccess 2\n")

    _write(incident_b / "metadata.json", metadata_b)
    _write(incident_b / "labels.json", labels_b)
    _write(incident_b / "failing_log.txt", "line a\nERROR b\nline c\n")

    split = {
        "name": "component_real_demo",
        "benchmark_group": "component_real",
        "version": "2026-04-12",
        "split_by": "repo",
        "train": [],
        "dev": ["INC2001", "INC2002"],
        "test": [],
    }
    _write(benchmark_root / "splits" / "demo.json", split)
    return benchmark_root


def test_load_benchmark_cases_reads_split(tmp_path):
    benchmark_root = _seed_benchmark_root(tmp_path)
    cases = load_benchmark_cases(
        benchmark_root=str(benchmark_root),
        split="splits/demo.json",
        partition="dev",
    )

    assert [case["incident_id"] for case in cases] == ["INC2001", "INC2002"]
    assert cases[0]["success_log_path"].endswith("success_log.txt")
    assert cases[1]["success_log_path"] is None


def test_evaluate_benchmark_split_and_write_predictions(tmp_path):
    benchmark_root = _seed_benchmark_root(tmp_path)
    remediator = _StubRemediator()
    repo_map_path = tmp_path / "repo_map.json"
    repo_checkout = tmp_path / "repos" / "demo-repo"
    repo_checkout.mkdir(parents=True)
    repo_map_path.write_text(json.dumps({"INC2001": str(repo_checkout)}), encoding="utf-8")

    report = evaluate_benchmark_split(
        remediator=remediator,
        benchmark_root=str(benchmark_root),
        split="splits/demo.json",
        partition="dev",
        repo_map_path=str(repo_map_path),
        use_success_logs=True,
        artifact_root=str(tmp_path / "artifacts"),
        model_name="gpt-4o-mini",
    )

    assert report["summary"]["num_cases"] == 2
    assert report["summary"]["num_completed_cases"] == 2
    assert report["benchmark_mode"] == "component"
    assert report["summary"]["benchmark_mode_counts"]["component"] == 2
    assert report["summary"]["repo_resolution_counts"]["mapped"] == 1
    assert report["summary"]["repo_resolution_counts"]["not_provided"] == 1
    assert remediator.calls[0]["method"] == "analyze"
    assert remediator.calls[0]["success_logs"] == ["success 1\nsuccess 2\n"]

    report_path = tmp_path / "report.json"
    predictions_path = tmp_path / "predictions.jsonl"
    write_benchmark_report(report, str(report_path))
    write_predictions_jsonl(report, str(predictions_path))

    loaded_report = load_benchmark_report(str(report_path))
    prediction_lines = predictions_path.read_text(encoding="utf-8").strip().splitlines()

    assert loaded_report["summary"]["num_cases"] == 2
    assert len(prediction_lines) == 2
    first_prediction = json.loads(prediction_lines[0])
    assert first_prediction["incident_id"] == "INC2001"
    assert first_prediction["rca"]["failure_class"] == "build_failure"
    case_artifact = json.loads((tmp_path / "artifacts" / "cases" / "INC2001" / "result.json").read_text(encoding="utf-8"))
    assert case_artifact["incident_id"] == "INC2001"
    assert case_artifact["run"]["benchmark_mode"] == "component"
    assert case_artifact["run"]["verification_profile"] == "strict"
    assert "execution" not in case_artifact
    assert "remediation" not in case_artifact
    assert "verification" not in case_artifact
    assert case_artifact["prediction"]["failure_class"] == "build_failure"
    assert case_artifact["result_summary"]["predicted_failure_class"] == "build_failure"
    assert case_artifact["result_summary"]["predicted_root_cause_label"] == "synthetic_root_cause"
    assert case_artifact["result_summary"]["predicted_root_cause_text"] == "synthetic root cause"


def test_evaluate_benchmark_split_resume_skips_completed_ok_cases(tmp_path):
    benchmark_root = _seed_benchmark_root(tmp_path)
    remediator = _StubRemediator()

    report = evaluate_benchmark_split(
        remediator=remediator,
        benchmark_root=str(benchmark_root),
        split="splits/demo.json",
        partition="dev",
        existing_report={
            "summary": {},
            "cases": [
                {
                    "incident_id": "INC2001",
                    "execution_status": "ok",
                    "benchmark_group": "component_real",
                    "source_case_id": "logsage:demo/pair_1",
                    "repo": "demo-repo",
                    "result": {
                        "rca": {"failure_class": "build_failure"},
                        "remediation": {},
                        "verification": {"status": "inconclusive"},
                    },
                }
            ],
        },
    )

    assert report["summary"]["num_cases"] == 2
    assert len(remediator.calls) == 1
    assert remediator.calls[0]["raw_log_text"].startswith("line a")


def test_evaluate_benchmark_split_full_mode_runs_full_pipeline(tmp_path):
    benchmark_root = _seed_benchmark_root(tmp_path)
    remediator = _StubRemediator()

    report = evaluate_benchmark_split(
        remediator=remediator,
        benchmark_root=str(benchmark_root),
        split="splits/demo.json",
        partition="dev",
        benchmark_mode="full",
        artifact_root=str(tmp_path / "artifacts"),
        model_name="gpt-4o-mini",
    )

    assert report["benchmark_mode"] == "full"
    assert report["summary"]["benchmark_mode_counts"]["full"] == 2
    assert remediator.calls[0]["method"] == "run"
    assert remediator.calls[0]["verification_profile"] == "strict"

    case_artifact = json.loads((tmp_path / "artifacts" / "cases" / "INC2001" / "result.json").read_text(encoding="utf-8"))
    assert case_artifact["run"]["benchmark_mode"] == "full"
    assert case_artifact["run"]["verification_profile"] == "strict"
    assert case_artifact["remediation"]["fix_type"] == "template_fix"
    assert case_artifact["verification"]["status"] == "inconclusive"


def test_evaluate_benchmark_split_batches_accumulate_prior_results(tmp_path):
    benchmark_root = _seed_benchmark_root(tmp_path)
    artifact_root = tmp_path / "artifacts"

    remediator_first = _StubRemediator()
    first_report = evaluate_benchmark_split(
        remediator=remediator_first,
        benchmark_root=str(benchmark_root),
        split="splits/demo.json",
        partition="dev",
        batch_size=1,
        batch_number=1,
        artifact_root=str(artifact_root),
        model_name="gpt-4o-mini",
    )

    assert first_report["summary"]["num_cases"] == 1
    assert [case["incident_id"] for case in first_report["cases"]] == ["INC2001"]
    assert len(remediator_first.calls) == 1

    remediator_second = _StubRemediator()
    second_report = evaluate_benchmark_split(
        remediator=remediator_second,
        benchmark_root=str(benchmark_root),
        split="splits/demo.json",
        partition="dev",
        existing_report=first_report,
        batch_size=1,
        batch_number=2,
        artifact_root=str(artifact_root),
        model_name="gpt-4o-mini",
    )

    assert second_report["summary"]["num_cases"] == 2
    assert [case["incident_id"] for case in second_report["cases"]] == ["INC2001", "INC2002"]
    assert len(remediator_second.calls) == 1
    assert remediator_second.calls[0]["raw_log_text"].startswith("line a")

    artifact_report = load_benchmark_report(str(artifact_root / "report.json"))
    assert [case["incident_id"] for case in artifact_report["cases"]] == ["INC2001", "INC2002"]


def test_default_benchmark_artifact_dir_uses_benchmark_exports(tmp_path):
    root = tmp_path / "benchmark"
    path = default_benchmark_artifact_dir(
        benchmark_root=str(root),
        split="splits/component_real_reviewed19_primary.json",
        partition="dev",
        model="gpt-4o-mini",
    )
    assert path == root / "exports" / "evaluations" / "component_real_reviewed19_primary__dev__gpt-4o-mini"
