import pytest

from gha_remediator.llm.github_models_client import GitHubModelsClient


def test_coerce_content_string():
    assert GitHubModelsClient._coerce_content_to_text("  {\"a\":1}  ") == '{"a":1}'


def test_coerce_content_list_chunks():
    content = [{"type": "text", "text": "{\"a\": 1}"}, {"type": "text", "text": "\n"}]
    assert "{\"a\": 1}" in GitHubModelsClient._coerce_content_to_text(content)


def test_extract_json_plain():
    text = '{"root_causes":["x"],"confidence":0.9}'
    assert GitHubModelsClient._extract_json_text(text) == text


def test_extract_json_markdown_fence():
    text = "```json\n{\"root_causes\":[\"x\"],\"confidence\":0.9}\n```"
    out = GitHubModelsClient._extract_json_text(text)
    assert out.startswith("{")
    assert out.endswith("}")


def test_extract_json_from_mixed_text():
    text = "Here is the result:\n{\"root_causes\":[\"x\"],\"confidence\":0.9}\nDone."
    out = GitHubModelsClient._extract_json_text(text)
    assert out == '{"root_causes":["x"],"confidence":0.9}'


def test_extract_json_raises_on_non_json():
    with pytest.raises(RuntimeError):
        GitHubModelsClient._extract_json_text("not json at all")
