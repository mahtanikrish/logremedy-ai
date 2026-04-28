import json

from gha_remediator import cli


def test_cli_build_arg_parser_registers_all_public_commands():
    parser = cli.build_arg_parser()
    choices = parser._subparsers._group_actions[0].choices

    assert set(choices) == {
        "run",
        "eval-synthetic",
        "eval-benchmark",
        "export-real-case",
        "inspect-context",
        "debug-plan-input",
    }


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
    assert payload["root_cause_label"] == "missing_python_dependency"
    assert payload["root_cause_text"] == "Missing Python dependency (module import failed)."
    assert payload["confidence"] is None
    assert payload["evidence_line_numbers"] == []
    assert payload["notes"] == []
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
    assert payload["root_cause_label"] == "missing_python_dependency"
    assert payload["root_cause_text"] == "Missing Python dependency (module import failed)."
    assert payload["confidence"] is None
    assert payload["evidence_line_numbers"] == []
    assert payload["notes"] == []
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


def test_cli_inspect_context_uses_shared_runtime_factory(monkeypatch, tmp_path, capsys):
    log_path = _write_log(tmp_path)
    captured = {}

    class _StubRemediator:
        def analyze(self, raw_log_text):
            from gha_remediator.types import RCAReport

            captured["raw_log_text"] = raw_log_text
            return RCAReport(
                failure_class="environment_dependency_failure",
                root_cause_label="missing_python_dependency",
                root_cause_text="Missing Python dependency (module import failed).",
                root_causes=["Missing Python dependency (module import failed)."],
                key_lines=[],
                blocks=[],
                metadata={},
            )

    def fake_build_remediator(**kwargs):
        captured["kwargs"] = kwargs
        return _StubRemediator()

    monkeypatch.setattr("gha_remediator.cli.build_remediator", fake_build_remediator)
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

    assert captured["kwargs"]["enable_llm"] is False
    payload = json.loads(capsys.readouterr().out)
    assert payload["failure_class"] == "environment_dependency_failure"
