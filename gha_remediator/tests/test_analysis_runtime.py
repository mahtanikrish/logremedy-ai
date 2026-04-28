from pathlib import Path

from gha_remediator.app_settings import AppSettings
from gha_remediator.services.analysis_runtime import (
    describe_kb,
    load_kb_for_settings,
    normalize_repo_path,
    run_synthetic_analysis_text,
)


def test_normalize_repo_path_preserves_blank_repo():
    assert normalize_repo_path("") == ""
    assert normalize_repo_path("   ") == ""


def test_normalize_repo_path_resolves_non_blank_repo(tmp_path):
    expected = str(Path(tmp_path).resolve())
    assert normalize_repo_path(str(tmp_path)) == expected


def test_load_kb_for_settings_reads_json_file(tmp_path):
    kb_file = tmp_path / "kb.json"
    kb_file.write_text(
        '[{"doc_id":"doc-1","title":"Custom Doc","text":"custom knowledge"}]',
        encoding="utf-8",
    )

    kb = load_kb_for_settings(AppSettings(knowledge_base_path=str(kb_file)))

    assert len(kb.docs) == 1
    assert kb.docs[0].title == "Custom Doc"


def test_describe_kb_reports_default_docs():
    payload = describe_kb(AppSettings())

    assert payload["configured"] is False
    assert payload["source"] == "default"
    assert payload["docCount"] > 0


def test_run_synthetic_analysis_text_uses_shared_runtime_factory(monkeypatch):
    captured = {}

    class _StubRemediator:
        def run(self, *, raw_log_text, repo, replay, job):
            captured["raw_log_text"] = raw_log_text
            captured["repo"] = repo
            captured["replay"] = replay
            captured["job"] = job
            return {"ok": True}

    def fake_build_remediator(**kwargs):
        captured["kwargs"] = kwargs
        return _StubRemediator()

    monkeypatch.setattr("gha_remediator.services.analysis_runtime.build_remediator", fake_build_remediator)
    monkeypatch.setattr(
        "gha_remediator.services.analysis_runtime.load_app_settings",
        lambda: AppSettings(),
    )

    result = run_synthetic_analysis_text("failure", "   ", "gpt-4o-mini")

    assert result == {"ok": True}
    assert captured["kwargs"]["model"] == "gpt-4o-mini"
    assert captured["kwargs"]["max_output_tokens"] == 2200
    assert captured["repo"] == ""
