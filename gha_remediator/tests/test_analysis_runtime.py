from pathlib import Path

from gha_remediator.app_settings import AppSettings
from gha_remediator.services.analysis_runtime import (
    describe_kb,
    load_kb_for_settings,
    normalize_repo_path,
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
