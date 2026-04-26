from gha_remediator.pipeline import GHARemediator
from gha_remediator.rag import KnowledgeBase
from gha_remediator.rca import run_rca
from gha_remediator import prompts


class _RcaStructuredLLM:
    def __init__(self):
        self.calls = []
        self.last_response_metadata = {
            "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        }

    def generate_json(self, *, system, user, schema_hint, cfg):
        self.calls.append({"system": system, "user": user, "schema_hint": schema_hint})
        if system == prompts.RCA_SYSTEM:
            return {
                "root_cause_label": "missing_dependency_in_ci_environment",
                "root_cause_text": "Missing dependency in CI environment.",
                "root_causes": ["Missing dependency in CI environment."],
                "confidence": 0.87,
                "evidence_line_numbers": [3, 5],
                "notes": ["requests is imported before installation."],
            }
        return {
            "fix_type": "llm_plan",
            "risk_level": "low",
            "patches": [],
            "commands": [],
            "assumptions": ["captured"],
            "rollback": [],
        }


class _WeakRcaLLM(_RcaStructuredLLM):
    def generate_json(self, *, system, user, schema_hint, cfg):
        self.calls.append({"system": system, "user": user, "schema_hint": schema_hint})
        if system == prompts.RCA_SYSTEM:
            return {
                "root_cause_label": "unknown_root_cause",
                "root_cause_text": "Not enough information to determine the root cause.",
                "root_causes": ["Not enough info from the log."],
                "confidence": 0.99,
                "evidence_line_numbers": [],
                "notes": ["The model could not determine a specific cause."],
        }
        return super().generate_json(system=system, user=user, schema_hint=schema_hint, cfg=cfg)


class _GuidanceOnlyPlanLLM(_RcaStructuredLLM):
    def generate_json(self, *, system, user, schema_hint, cfg):
        self.calls.append({"system": system, "user": user, "schema_hint": schema_hint})
        if system == prompts.RCA_SYSTEM:
            return {
                "root_cause_label": "extractor_class_name_mismatch",
                "root_cause_text": "The extractor class name does not match the expected format.",
                "root_causes": [
                    "The extractor class name does not match the expected format.",
                    "AssertionError in the extractor naming test indicates a casing mismatch.",
                ],
                "confidence": 0.96,
                "evidence_line_numbers": [2],
                "notes": ["Review the expected and actual extractor class names."],
            }
        return {
            "fix_type": "code_fix",
            "risk_level": "low",
            "patches": [],
            "commands": [],
            "guidance": [
                "Inspect the failing assertion and compare the expected extractor class name with the implemented class name.",
                "Rerun `make test` after adjusting the class name casing.",
            ],
            "assumptions": ["The failure is caused by class name casing."],
            "rollback": ["Revert the rename if the test still fails."],
        }


def _raw_log() -> str:
    return "\n".join(
        [
            "Step: Run tests",
            "Traceback (most recent call last):",
            '  File "app.py", line 1, in <module>',
            "    import requests",
            "ModuleNotFoundError: No module named 'requests'",
            "Error: Process completed with exit code 1.",
        ]
    )


def _dependabot_log() -> str:
    return "\n".join(
        [
            "Starting security update job for ColorlibHQ/AdminLTE",
            "Checking if prismjs 1.29.0 needs updating",
            "Latest version is 1.30.0",
            "The latest possible version that can be installed is 1.29.0 because of the following conflicting dependencies:",
            "@astrojs/mdx@4.0.6 requires prismjs@^1.29.0 via a transitive dependency on @astrojs/prism@3.2.0",
            "astro@5.1.7 requires prismjs@^1.29.0 via a transitive dependency on @astrojs/prism@3.2.0",
            "Dependabot encountered '1' error(s) during execution, please check the logs for more details.",
            "| transitive_update_not_possible |",
            "##[error]Dependabot encountered an error performing the update",
        ]
    )


def test_run_rca_preserves_structured_llm_fields():
    llm = _RcaStructuredLLM()

    report = run_rca(_raw_log(), llm=llm)

    assert report.root_cause_label == "missing_dependency_in_ci_environment"
    assert report.root_cause_text == "Missing dependency in CI environment."
    assert report.root_causes == ["Missing dependency in CI environment."]
    assert report.confidence == 0.87
    assert report.evidence_line_numbers == [3, 5]
    assert report.notes == ["requests is imported before installation."]
    assert report.metadata["root_cause_label"] == "missing_dependency_in_ci_environment"
    assert report.metadata["root_cause_text"] == "Missing dependency in CI environment."
    assert report.metadata["llm_confidence"] == 0.87
    assert report.metadata["evidence_line_numbers"] == [3, 5]
    assert report.metadata["notes"] == ["requests is imported before installation."]
    assert report.metadata["llm"]["usage"]["total_tokens"] == 18


def test_run_rca_raw_tail_sets_preprocessing_metadata():
    llm = _RcaStructuredLLM()

    report = run_rca(_raw_log(), llm=llm, preprocessing_mode="raw_tail")

    assert report.metadata["preprocessing_mode"] == "raw_tail"
    assert report.metadata["raw_log_approx_tokens"] > 0
    assert report.metadata["selected_input_approx_tokens"] > 0
    assert report.metadata["curated_input_approx_tokens"] is None
    assert report.metadata["num_blocks"] == 1


def test_run_rca_falls_back_when_llm_output_is_weak():
    llm = _WeakRcaLLM()

    report = run_rca(_raw_log(), llm=llm)

    assert report.root_cause_label == "missing_python_dependency"
    assert report.root_cause_text == "Missing Python dependency (module import failed)."
    assert report.root_causes == ["Missing Python dependency (module import failed)."]
    assert report.confidence is None
    assert report.metadata["rca_mode"] == "heuristic_fallback_from_llm"
    assert report.metadata["llm_rca_rejected"] is True
    assert report.metadata["llm_root_cause_label"] == "unknown_root_cause"


def test_pipeline_output_includes_structured_rca_fields():
    llm = _RcaStructuredLLM()
    remediator = GHARemediator(kb=KnowledgeBase([]), llm=llm)

    result = remediator.run(raw_log_text=_raw_log(), repo=None, replay=False, job=None)

    assert result["rca"]["root_cause_label"] == "missing_dependency_in_ci_environment"
    assert result["rca"]["root_cause_text"] == "Missing dependency in CI environment."
    assert result["rca"]["confidence"] == 0.87
    assert result["rca"]["evidence_line_numbers"] == [3, 5]
    assert result["rca"]["notes"] == ["requests is imported before installation."]
    assert result["rca"]["metadata"]["llm"]["usage"]["prompt_tokens"] == 11
    assert result["verification"]["status"] == "inconclusive"
    assert result["verification"]["reason"] == "verification skipped: repo not provided"


def test_run_rca_identifies_dependabot_transitive_dependency_conflict():
    report = run_rca(_dependabot_log(), llm=None)

    assert report.failure_class == "environment_dependency_failure"
    assert report.root_cause_label == "dependabot_transitive_dependency_conflict"
    assert "Dependabot could not update prismjs" in report.root_cause_text
    assert report.metadata["num_blocks"] >= 1


def test_pipeline_preserves_guidance_only_llm_plan():
    llm = _GuidanceOnlyPlanLLM()
    remediator = GHARemediator(kb=KnowledgeBase([]), llm=llm)
    raw_log = "\n".join(
        [
            "Ensure extractor classes are named CategorySubcategoryExtractor ... FAIL",
            "FAIL: test_names (test_extractor.TestExtractorModule)",
            "AssertionError: 'HatenablogArchiveExtractor' != 'HatenaBlogArchiveExtractor'",
            "make: *** [Makefile:22: test] Error 1",
        ]
    )

    result = remediator.run(raw_log_text=raw_log, repo=None, replay=False, job=None)

    assert result["remediation"]["fix_type"] == "code_fix"
    assert result["remediation"]["commands"] == []
    assert len(result["remediation"]["guidance"]) == 2
    assert result["remediation"]["evidence"]["planner"] == "llm"
    assert result["verification"]["status"] == "inconclusive"


def test_pipeline_suppresses_llm_patches_without_repo_context():
    class _PatchyNoRepoLLM(_RcaStructuredLLM):
        def generate_json(self, *, system, user, schema_hint, cfg):
            self.calls.append({"system": system, "user": user, "schema_hint": schema_hint})
            if system == prompts.RCA_SYSTEM:
                return {
                    "root_cause_label": "extractor_class_name_mismatch",
                    "root_cause_text": "The extractor class name does not match the expected format.",
                    "root_causes": ["The extractor class name does not match the expected format."],
                    "confidence": 0.96,
                    "evidence_line_numbers": [2],
                    "notes": ["Review the expected and actual extractor class names."],
                }
            return {
                "fix_type": "code_fix",
                "risk_level": "low",
                "patches": [
                    {
                        "path": "test/test_extractor.py",
                        "diff": "--- test/test_extractor.py\n+++ test/test_extractor.py\n@@ -1 +1 @@\n-old\n+new\n",
                    }
                ],
                "commands": [],
                "guidance": ["Inspect the expected class name casing before changing the code."],
                "assumptions": ["The failure is caused by class name casing."],
                "rollback": ["Revert the rename if the test still fails."],
            }

    llm = _PatchyNoRepoLLM()
    remediator = GHARemediator(kb=KnowledgeBase([]), llm=llm)
    raw_log = "\n".join(
        [
            "Ensure extractor classes are named CategorySubcategoryExtractor ... FAIL",
            "FAIL: test_names (test_extractor.TestExtractorModule)",
            "AssertionError: 'HatenablogArchiveExtractor' != 'HatenaBlogArchiveExtractor'",
            "make: *** [Makefile:22: test] Error 1",
        ]
    )

    result = remediator.run(raw_log_text=raw_log, repo=None, replay=False, job=None)

    assert result["remediation"]["patches"] == []
    assert result["remediation"]["guidance"] == [
        "Inspect the expected class name casing before changing the code."
    ]
    assert result["remediation"]["evidence"]["patches_suppressed"]["count"] == 1
