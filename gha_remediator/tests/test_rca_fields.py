from gha_remediator.pipeline import GHARemediator
from gha_remediator.rag import KnowledgeBase
from gha_remediator.rca import run_rca
from gha_remediator import prompts


class _RcaStructuredLLM:
    def __init__(self):
        self.calls = []

    def generate_json(self, *, system, user, schema_hint, cfg):
        self.calls.append({"system": system, "user": user, "schema_hint": schema_hint})
        if system == prompts.RCA_SYSTEM:
            return {
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


def test_run_rca_preserves_structured_llm_fields():
    llm = _RcaStructuredLLM()

    report = run_rca(_raw_log(), llm=llm)

    assert report.root_causes == ["Missing dependency in CI environment."]
    assert report.confidence == 0.87
    assert report.evidence_line_numbers == [3, 5]
    assert report.notes == ["requests is imported before installation."]
    assert report.metadata["llm_confidence"] == 0.87
    assert report.metadata["evidence_line_numbers"] == [3, 5]
    assert report.metadata["notes"] == ["requests is imported before installation."]


def test_pipeline_output_includes_structured_rca_fields():
    llm = _RcaStructuredLLM()
    remediator = GHARemediator(kb=KnowledgeBase([]), llm=llm)

    result = remediator.run(raw_log_text=_raw_log(), repo=None, replay=False, job=None)

    assert result["rca"]["confidence"] == 0.87
    assert result["rca"]["evidence_line_numbers"] == [3, 5]
    assert result["rca"]["notes"] == ["requests is imported before installation."]
    assert result["verification"]["status"] == "inconclusive"
    assert result["verification"]["reason"] == "verification skipped: repo not provided"
