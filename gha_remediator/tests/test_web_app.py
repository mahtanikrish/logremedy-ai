from gha_remediator import web_app


def test_web_app_arg_parser_supports_helpful_defaults():
    parser = web_app.build_arg_parser()

    args = parser.parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8000


def test_synthetic_route_preserves_blank_repo(monkeypatch):
    app = web_app.create_app()
    captured = {}

    def fake_run_synthetic_analysis_text(*, raw_log_text, repo, model):
        captured["raw_log_text"] = raw_log_text
        captured["repo"] = repo
        captured["model"] = model
        return {
            "rca": {},
            "remediation": {},
            "verification": {},
        }

    monkeypatch.setattr(web_app, "run_synthetic_analysis_text", fake_run_synthetic_analysis_text)

    client = app.test_client()
    response = client.post(
        "/api/analyze/synthetic",
        json={"rawLogText": "failure", "repo": "", "model": "gpt-4o-mini"},
    )

    assert response.status_code == 200
    assert captured["repo"] == ""


def test_github_route_preserves_blank_verify_repo(monkeypatch):
    app = web_app.create_app()
    captured = {}

    def fake_run_github_analysis(*, repo_name, run_id, verify_repo, model):
        captured["repo_name"] = repo_name
        captured["run_id"] = run_id
        captured["verify_repo"] = verify_repo
        captured["model"] = model
        return (
            {"rca": {}, "remediation": {}, "verification": {}},
            123,
            "raw log",
        )

    monkeypatch.setattr(web_app, "run_github_analysis", fake_run_github_analysis)

    client = app.test_client()
    response = client.post(
        "/api/analyze/github",
        json={"repoName": "owner/name", "runId": "", "verifyRepo": "", "model": "gpt-4o-mini"},
    )

    assert response.status_code == 200
    assert captured["verify_repo"] == ""


def test_settings_route_round_trips(monkeypatch, tmp_path):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setenv("GHA_REMEDIATOR_SETTINGS_PATH", str(settings_file))

    app = web_app.create_app()
    client = app.test_client()

    response = client.post(
        "/api/settings",
        json={
            "knowledgeBasePath": "/tmp/kb.json",
            "envFilePath": "/tmp/.env",
        },
    )

    assert response.status_code == 200
    saved = response.get_json()
    assert saved["settings"]["knowledgeBasePath"] == "/tmp/kb.json"
    assert saved["settings"]["envFilePath"] == "/tmp/.env"

    loaded = client.get("/api/settings")
    assert loaded.status_code == 200
    payload = loaded.get_json()
    assert payload["settings"]["knowledgeBasePath"] == "/tmp/kb.json"
    assert payload["settings"]["envFilePath"] == "/tmp/.env"
