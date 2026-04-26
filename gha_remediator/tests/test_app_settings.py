from pathlib import Path

from gha_remediator.app_settings import (
    AppSettings,
    load_app_settings,
    parse_env_file,
    resolve_github_token,
    save_app_settings,
)


def test_save_and_load_app_settings(monkeypatch, tmp_path):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setenv("GHA_REMEDIATOR_SETTINGS_PATH", str(settings_file))

    saved = save_app_settings(
        AppSettings(
            knowledge_base_path="/tmp/kb.json",
            env_file_path="/tmp/.env",
        )
    )
    loaded = load_app_settings()

    assert saved == loaded
    assert loaded.knowledge_base_path == "/tmp/kb.json"
    assert loaded.env_file_path == "/tmp/.env"


def test_parse_env_file_supports_export_and_quotes(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                'export GITHUB_TOKEN="abc123"',
                "OTHER=value",
            ]
        ),
        encoding="utf-8",
    )

    values = parse_env_file(str(env_file))

    assert values["GITHUB_TOKEN"] == "abc123"
    assert values["OTHER"] == "value"


def test_resolve_github_token_uses_env_file_when_environment_missing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("GITHUB_TOKEN=file-token\n", encoding="utf-8")

    token, source = resolve_github_token(
        settings=AppSettings(env_file_path=str(env_file)),
        environ={},
    )

    assert token == "file-token"
    assert source == "env_file"
