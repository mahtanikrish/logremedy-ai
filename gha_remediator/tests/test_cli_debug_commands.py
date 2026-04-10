import json

from gha_remediator import cli


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _seed_repo(tmp_path):
    _write(
        tmp_path / ".github" / "workflows" / "ci.yml",
        "\n".join(
            [
                "name: CI",
                "on: [push]",
                "jobs:",
                "  build:",
                "    runs-on: ubuntu-latest",
                "    steps:",
                "      - uses: actions/checkout@v4",
                "      - uses: actions/setup-python@v5",
                "        with:",
                '          python-version: "3.11"',
                "      - run: python app.py",
            ]
        ),
    )
    _write(
        tmp_path / "app.py",
        "\n".join(
            [
                "import requests",
                "",
                "print(requests.__version__)",
            ]
        ),
    )


def _write_log(tmp_path):
    log_path = tmp_path / "failure.log"
    log_path.write_text(
        "\n".join(
            [
                "Step: Run application",
                "Traceback (most recent call last):",
                '  File "app.py", line 1, in <module>',
                "    import requests",
                "ModuleNotFoundError: No module named 'requests'",
                "Error: Process completed with exit code 1.",
            ]
        ),
        encoding="utf-8",
    )
    return log_path


def test_cli_inspect_context_outputs_repo_context(monkeypatch, tmp_path, capsys):
    _seed_repo(tmp_path)
    log_path = _write_log(tmp_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "gha-remediator",
            "inspect-context",
            "--log",
            str(log_path),
            "--repo",
            str(tmp_path),
        ],
    )

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["failure_class"] == "environment_dependency_failure"
    assert payload["repo_context"]["workflow_files"] == [".github/workflows/ci.yml"]
    assert payload["repo_context"]["candidate_files"][0]["path"] == "app.py"
    assert "Detected manifests: none" in payload["repo_context_summary"]


def test_cli_debug_plan_input_outputs_prompt(monkeypatch, tmp_path, capsys):
    _seed_repo(tmp_path)
    log_path = _write_log(tmp_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "gha-remediator",
            "debug-plan-input",
            "--log",
            str(log_path),
            "--repo",
            str(tmp_path),
        ],
    )

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["failure_class"] == "environment_dependency_failure"
    assert "Repository context:" in payload["user_prompt"]
    assert ".github/workflows/ci.yml" in payload["user_prompt"]
    assert "app.py" in payload["user_prompt"]


def test_cli_inspect_context_without_repo_reports_scan_error(monkeypatch, tmp_path, capsys):
    log_path = _write_log(tmp_path)

    monkeypatch.setattr(
        "sys.argv",
        [
            "gha-remediator",
            "inspect-context",
            "--log",
            str(log_path),
        ],
    )

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["repo_context"]["metadata"]["scan_error"] == "repo not provided"
    assert payload["repo_context_summary"].startswith("Repo root: (not provided)")
