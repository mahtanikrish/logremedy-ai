import pytest

from gha_remediator.llm.base import LLMConfig
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


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"root_causes":["x"],"confidence":0.9}'
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }


def test_generate_json_legacy_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("gha_remediator.llm.github_models_client.requests.post", fake_post)
    client = GitHubModelsClient(token="test-token")
    out = client.generate_json(
        system="sys",
        user="usr",
        schema_hint="{}",
        cfg=LLMConfig(model="gpt-4o-mini", max_output_tokens=123),
    )

    assert out["root_causes"] == ["x"]
    assert captured["url"] == (
        "https://models.inference.ai.azure.com/openai/deployments/gpt-4o-mini/chat/completions"
        "?api-version=2024-02-15-preview"
    )
    assert captured["headers"]["api-key"] == "test-token"
    assert captured["json"]["model"] == "gpt-4o-mini"
    assert captured["json"]["max_tokens"] == 123
    assert client.last_response_metadata["endpoint"] == "legacy"


def test_generate_json_modern_endpoint(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("gha_remediator.llm.github_models_client.requests.post", fake_post)
    client = GitHubModelsClient(token="test-token")
    out = client.generate_json(
        system="sys",
        user="usr",
        schema_hint="{}",
        cfg=LLMConfig(
            model="openai/gpt-5-mini",
            max_output_tokens=321,
            reasoning_effort="medium",
        ),
    )

    assert out["root_causes"] == ["x"]
    assert captured["url"] == "https://models.github.ai/inference/chat/completions"
    assert captured["headers"]["Accept"] == "application/vnd.github+json"
    assert captured["headers"]["Authorization"] == "Bearer test-token"
    assert captured["headers"]["X-GitHub-Api-Version"] == "2022-11-28"
    assert captured["json"]["model"] == "openai/gpt-5-mini"
    assert captured["json"]["max_tokens"] == 321
    assert captured["json"]["reasoning_effort"] == "medium"
    assert client.last_response_metadata["endpoint"] == "modern"
