from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
import subprocess

from gha_remediator.types import (
    LogBlock,
    LogLine,
    Patch,
    RCAReport,
    RemediationPlan,
    RepoCandidateFile,
    RepoContext,
)
from gha_remediator.verification.replay import ReplayConfig
from gha_remediator.verification.verify import verify_plan


def _make_plan(
    *,
    patches: list[Patch] | None = None,
    commands: list[str] | None = None,
    fix_type: str = "custom_fix",
    failure_class: str = "environment_dependency_failure",
) -> RemediationPlan:
    return RemediationPlan(
        failure_class=failure_class,
        fix_type=fix_type,
        patches=patches or [],
        commands=commands or [],
        assumptions=[],
        rollback=[],
        risk_level="low",
        evidence={},
    )


def _make_report(
    *,
    failure_class: str = "build_failure",
    label: str | None = None,
    text: str | None = None,
    lines: list[str] | None = None,
) -> RCAReport:
    log_lines = [LogLine(idx, raw) for idx, raw in enumerate(lines or ["failure"], start=1)]
    return RCAReport(
        failure_class=failure_class,
        key_lines=log_lines,
        blocks=[LogBlock(start=1, end=len(log_lines), lines=log_lines)],
        root_causes=[text or "failure"],
        root_cause_label=label,
        root_cause_text=text,
        metadata={},
    )


def _modify_patch(path: str, before: str, after: str) -> Patch:
    diff = "".join(
        unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )
    return Patch(path=path, diff=diff)


def _add_file_patch(path: str, content: str) -> Patch:
    diff = "".join(
        unified_diff(
            [],
            content.splitlines(keepends=True),
            fromfile="/dev/null",
            tofile=path,
        )
    )
    return Patch(path=path, diff=diff)


def _capability(result) -> dict:
    capability = result.evidence.get("capability")
    assert isinstance(capability, dict)
    expected_keys = {
        "selected_validator",
        "selection_reason",
        "matching_validators",
        "suppressed_validators",
        "availability",
        "outcome",
        "summary",
        "execution_mode",
        "fallback_used",
    }
    assert expected_keys <= capability.keys()
    return capability


def _gate(result, name: str) -> dict:
    return next(gate for gate in result.evidence["gates"] if gate["name"] == name)


def test_capability_exists_on_precondition_rejection():
    plan = _make_plan()

    result = verify_plan(plan, repo="/tmp/this-path-does-not-exist")

    capability = _capability(result)
    assert result.status == "rejected_precondition"
    assert capability["selected_validator"] == "none"
    assert capability["outcome"] == "rejected"
    assert capability["execution_mode"] == "deterministic"


def test_capability_exists_on_adapter_inconclusive(monkeypatch, tmp_path):
    target = tmp_path / "timeseries"
    target.mkdir()
    before = '"orjson~=3.9",  # use faster JSON implemention in GluonTS\n'
    after = '"orjson~=3.9",  # use faster JSON implementation in GluonTS\n'
    (target / "setup.py").write_text(before, encoding="utf-8")
    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda _name: None)

    plan = _make_plan(
        patches=[_modify_patch("timeseries/setup.py", before, after)],
        fix_type="spelling_correction",
    )
    report = _make_report(
        label="codespell_error",
        text="Codespell detected a spelling error in the codebase.",
        lines=["##[error]./timeseries/setup.py:39: implemention ==> implementation"],
    )
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["timeseries/setup.py"],
        manifests=["timeseries/setup.py"],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="timeseries/setup.py", reason="error location from log")],
    )

    result = verify_plan(plan, repo=str(tmp_path), report=report, repo_context=repo_context)

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "codespell"
    assert capability["availability"] == "unavailable"
    assert capability["outcome"] == "inconclusive"


def test_capability_exists_on_verified_result(monkeypatch, tmp_path):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("flask==3.0.0\n", encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", "flask==3.0.0\n", "requests==2.32.0\n")],
    )

    def fake_replay_with_act(repo, cfg):
        return "verified", {
            "attempted": True,
            "tool_available": True,
            "cmd": ["act", "push"],
            "job": None,
            "event": "push",
            "workdir": repo,
            "returncode": 0,
            "classification": "passed",
            "stdout_tail": "",
            "stderr_tail": "",
        }

    monkeypatch.setattr("gha_remediator.verification.verify.replay_with_act", fake_replay_with_act)

    result = verify_plan(plan, repo=str(tmp_path), replay_cfg=ReplayConfig())

    capability = _capability(result)
    assert result.status == "verified"
    assert capability["outcome"] == "verified"
    assert capability["execution_mode"] == "replay"


def test_static_yaml_parser_missing_is_unavailable_not_failure(monkeypatch, tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow_path = workflow_dir / "ci.yml"
    original = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n"
    updated = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    workflow_path.write_text(original, encoding="utf-8")

    monkeypatch.setattr("gha_remediator.verification.static_checks.yaml", None)
    monkeypatch.setattr("gha_remediator.verification.adapters.yaml", None)
    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda _name: None)

    plan = _make_plan(
        patches=[_modify_patch(".github/workflows/ci.yml", original, updated)],
    )

    result = verify_plan(plan, repo=str(tmp_path))

    static_checks = result.evidence["static"]["checks"]
    yaml_check = next(check for check in static_checks if check["type"] == "yaml_parse")
    capability = _capability(result)
    assert yaml_check["available"] is False
    assert yaml_check["ok"] is None
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "workflow_yaml"
    assert capability["availability"] == "unavailable"


def test_workflow_validation_without_actionlint_uses_reduced_fallback(monkeypatch, tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow_path = workflow_dir / "ci.yml"
    original = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n"
    updated = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps:\n      - run: echo hi\n"
    workflow_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda _name: None)

    plan = _make_plan(
        patches=[_modify_patch(".github/workflows/ci.yml", original, updated)],
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "accepted"
    assert capability["selected_validator"] == "workflow_yaml"
    assert capability["availability"] == "reduced"
    assert capability["fallback_used"] is True
    assert result.reason == "accepted under reduced validator workflow_yaml"


def test_workflow_yaml_malformed_structure_fails_without_actionlint(monkeypatch, tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow_path = workflow_dir / "ci.yml"
    original = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n"
    updated = "on: push\njobs:\n  build:\n    steps: bad\n"
    workflow_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda _name: None)

    plan = _make_plan(
        patches=[_modify_patch(".github/workflows/ci.yml", original, updated)],
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "rejected_adapter_check"
    assert capability["selected_validator"] == "workflow_yaml"
    assert capability["outcome"] == "rejected"


def test_patch_apply_normalizes_dot_slash_headers(tmp_path):
    target = tmp_path / "docs" / "source"
    target.mkdir(parents=True)
    original = "value = 1\n"
    updated = "value = 2\n"
    file_path = target / "conf.py"
    file_path.write_text(original, encoding="utf-8")
    patch = _modify_patch("./docs/source/conf.py", original, updated)
    patch.path = "docs/source/conf.py"
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["docs/source/conf.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="docs/source/conf.py", reason="error location from log")],
    )

    result = verify_plan(
        _make_plan(patches=[patch]),
        repo=str(tmp_path),
        repo_context=repo_context,
    )

    patch_gate = _gate(result, "patch_apply")
    assert result.status == "accepted"
    assert patch_gate["details"]["canonicalization"][0]["diff_rewritten"] is True
    assert patch_gate["details"]["canonicalization"][0]["canonical_path"] == "docs/source/conf.py"


def test_patch_apply_normalizes_git_style_headers(tmp_path):
    target = tmp_path / "pkg"
    target.mkdir(parents=True)
    original = "value = 1\n"
    updated = "value = 2\n"
    file_path = target / "app.py"
    file_path.write_text(original, encoding="utf-8")
    diff = (
        "diff --git a/./pkg/app.py b/./pkg/app.py\n"
        "--- a/./pkg/app.py\n"
        "+++ b/./pkg/app.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )
    patch = Patch(path="pkg/app.py", diff=diff)
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["pkg/app.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="pkg/app.py", reason="error location from log")],
    )

    result = verify_plan(
        _make_plan(patches=[patch]),
        repo=str(tmp_path),
        repo_context=repo_context,
    )

    patch_gate = _gate(result, "patch_apply")
    assert result.status == "accepted"
    assert patch_gate["details"]["canonicalization"][0]["git_header_rewrites"]


def test_patch_apply_rejects_ambiguous_hunk_after_canonicalization(tmp_path):
    target = tmp_path / "pkg"
    target.mkdir(parents=True)
    file_path = target / "app.py"
    file_path.write_text("value = 1\n", encoding="utf-8")
    patch = Patch(
        path="pkg/app.py",
        diff=(
            "--- ./pkg/app.py\n"
            "+++ ./pkg/app.py\n"
            "@@ -1 +1 @@\n"
            "-value = 9\n"
            "+value = 2\n"
        ),
    )
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["pkg/app.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="pkg/app.py", reason="error location from log")],
    )

    result = verify_plan(
        _make_plan(patches=[patch]),
        repo=str(tmp_path),
        repo_context=repo_context,
    )

    assert result.status == "rejected_unappliable"
    assert result.evidence["canonicalization"]["canonical_path"] == "pkg/app.py"


def test_grounding_promotes_unique_partial_candidate_to_strong_match(tmp_path):
    target = tmp_path / "libqtile"
    target.mkdir(parents=True)
    original = "value = 1\n"
    updated = "value = 2\n"
    file_path = target / "config.py"
    file_path.write_text(original, encoding="utf-8")
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["libqtile/config.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="config.py", reason="path referenced in log")],
    )

    result = verify_plan(
        _make_plan(patches=[_modify_patch("libqtile/config.py", original, updated)]),
        repo=str(tmp_path),
        repo_context=repo_context,
    )

    grounding_gate = _gate(result, "grounding")
    patch_grounding = grounding_gate["details"]["patch_grounding"][0]
    assert result.status == "accepted"
    assert patch_grounding["strength"] == "strong"
    assert patch_grounding["promotion"]["candidate_path"] == "config.py"
    assert patch_grounding["promotion"]["resolved_path"] == "libqtile/config.py"


def test_grounding_rejects_ambiguous_partial_candidate(tmp_path):
    left = tmp_path / "libqtile"
    right = tmp_path / "other"
    left.mkdir(parents=True)
    right.mkdir(parents=True)
    (left / "config.py").write_text("value = 1\n", encoding="utf-8")
    (right / "config.py").write_text("value = 1\n", encoding="utf-8")
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["libqtile/config.py", "other/config.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="config.py", reason="path referenced in log")],
    )

    result = verify_plan(
        _make_plan(patches=[_modify_patch("libqtile/config.py", "value = 1\n", "value = 2\n")]),
        repo=str(tmp_path),
        repo_context=repo_context,
    )

    assert result.status == "rejected_grounding"


def test_python_dependency_manifest_accepts_valid_requirement(tmp_path):
    req_path = tmp_path / "requirements.txt"
    original = "flask==3.0.0\n"
    updated = "requests>=2.31.0\n"
    req_path.write_text(original, encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", original, updated)],
        fix_type="python_add_dependency",
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "accepted"
    assert capability["selected_validator"] == "python_dependency_manifest"
    assert capability["availability"] == "available"


def test_python_dependency_manifest_rejects_malformed_requirement(tmp_path):
    req_path = tmp_path / "requirements.txt"
    original = "flask==3.0.0\n"
    updated = "requests>=\n"
    req_path.write_text(original, encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", original, updated)],
        fix_type="python_add_dependency",
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "rejected_adapter_check"
    assert capability["selected_validator"] == "python_dependency_manifest"


def test_python_dependency_manifest_unsupported_syntax_is_inconclusive(tmp_path):
    req_path = tmp_path / "requirements.txt"
    original = "flask==3.0.0\n"
    updated = "-r base.txt\n"
    req_path.write_text(original, encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", original, updated)],
        fix_type="python_add_dependency",
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "python_dependency_manifest"
    assert capability["availability"] == "reduced"


def test_python_dependency_manifest_missing_packaging_is_inconclusive(monkeypatch, tmp_path):
    req_path = tmp_path / "requirements.txt"
    original = "flask==3.0.0\n"
    updated = "requests>=2.31.0\n"
    req_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("gha_remediator.verification.adapters.Requirement", None)
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", original, updated)],
        fix_type="python_add_dependency",
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "python_dependency_manifest"
    assert capability["availability"] == "unavailable"


def test_dependency_fix_setup_py_is_inconclusive(tmp_path):
    setup_path = tmp_path / "setup.py"
    original = "install_requires = []\n"
    updated = "install_requires = ['requests>=2']\n"
    setup_path.write_text(original, encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("setup.py", original, updated)],
        fix_type="python_add_dependency",
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "python_dependency_manifest"


def test_non_dependency_setup_py_routes_to_python_source(tmp_path):
    setup_path = tmp_path / "setup.py"
    original = "value = 1\n"
    updated = "value = 2\n"
    setup_path.write_text(original, encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("setup.py", original, updated)],
        fix_type="custom_fix",
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "accepted"
    assert capability["selected_validator"] == "python_source"
    assert "python_dependency_manifest" not in capability["suppressed_validators"]


def test_python_quality_target_runs_ruff_on_grounded_file(monkeypatch, tmp_path):
    target = tmp_path / "src"
    target.mkdir()
    file_path = target / "mod.py"
    file_path.write_text("import os\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_which(name):
        return f"/usr/bin/{name}" if name == "ruff" else None

    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", fake_which)
    monkeypatch.setattr(
        "gha_remediator.verification.adapters._run_command",
        lambda cmd, *, cwd, timeout_s: (
            seen.update({"cmd": cmd, "cwd": cwd}) or {"status": "ok", "process": subprocess.CompletedProcess(cmd, 0, "", "")}
        ),
    )

    report = _make_report(
        label="ruff_import_sort_violation",
        text="Ruff I001 import order failure",
        lines=["I001 import block is un-sorted or un-formatted"],
    )
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["src/mod.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="src/mod.py", reason="error location from log")],
    )

    result = verify_plan(
        _make_plan(patches=[_modify_patch("src/mod.py", "import os\n", "import sys\n")], commands=["make quality"]),
        repo=str(tmp_path),
        report=report,
        repo_context=repo_context,
    )

    capability = _capability(result)
    assert result.status == "accepted"
    assert capability["selected_validator"] == "python_quality_target"
    assert seen["cmd"] == ["/usr/bin/ruff", "check", "--select", "I", "src/mod.py"]


def test_python_quality_target_uses_pre_commit_fallback(monkeypatch, tmp_path):
    target = tmp_path / "libqtile"
    target.mkdir()
    file_path = target / "config.py"
    file_path.write_text("value = 1\n", encoding="utf-8")

    def fake_which(name):
        if name == "flake8":
            return None
        if name == "pre-commit":
            return "/usr/bin/pre-commit"
        return None

    seen: dict[str, object] = {}

    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", fake_which)
    monkeypatch.setattr(
        "gha_remediator.verification.adapters._run_command",
        lambda cmd, *, cwd, timeout_s: (
            seen.update({"cmd": cmd, "cwd": cwd}) or {"status": "ok", "process": subprocess.CompletedProcess(cmd, 0, "", "")}
        ),
    )

    report = _make_report(
        label="flake8_invalid_escape_sequence_docstring",
        text="flake8 reports W605 invalid escape sequence",
        lines=["W605 invalid escape sequence"],
    )
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["libqtile/config.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="config.py", reason="path referenced in log")],
    )

    result = verify_plan(
        _make_plan(patches=[_modify_patch("libqtile/config.py", "value = 1\n", "value = 2\n")], commands=["pre-commit run --all-files"]),
        repo=str(tmp_path),
        report=report,
        repo_context=repo_context,
    )

    capability = _capability(result)
    assert result.status == "accepted"
    assert capability["selected_validator"] == "python_quality_target"
    assert capability["fallback_used"] is True
    assert capability["availability"] == "reduced"
    assert seen["cmd"] == ["/usr/bin/pre-commit", "run", "--files", "libqtile/config.py"]


def test_python_quality_target_missing_tool_is_inconclusive(monkeypatch, tmp_path):
    target = tmp_path / "src"
    target.mkdir()
    file_path = target / "mod.py"
    file_path.write_text("import os\n", encoding="utf-8")
    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda _name: None)

    report = _make_report(
        label="isort_import_order_violation",
        text="isort import order failure",
    )
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["src/mod.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="src/mod.py", reason="error location from log")],
    )

    result = verify_plan(
        _make_plan(patches=[_modify_patch("src/mod.py", "import os\n", "import sys\n")], commands=["make quality"]),
        repo=str(tmp_path),
        report=report,
        repo_context=repo_context,
    )

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "python_quality_target"
    assert capability["availability"] == "unavailable"


def test_broad_command_without_narrow_validator_is_inconclusive(monkeypatch, tmp_path):
    target = tmp_path / "src"
    target.mkdir()
    file_path = target / "mod.py"
    file_path.write_text("value = 1\n", encoding="utf-8")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("sandbox should not run for broad fallback commands")

    monkeypatch.setattr("gha_remediator.verification.verify.verify_commands_locally", fail_if_called)
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["src/mod.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="src/mod.py", reason="error location from log")],
    )

    result = verify_plan(
        _make_plan(
            patches=[_modify_patch("src/mod.py", "value = 1\n", "value = 2\n")],
            commands=["make quality"],
        ),
        repo=str(tmp_path),
        repo_context=repo_context,
        report=_make_report(text="quality job failed"),
    )

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "python_quality_target"
    assert capability["summary"] == "no narrow deterministic validator exists for the Python quality failure"


def test_pytest_target_reuses_existing_grounded_pytest_command(monkeypatch, tmp_path):
    test_file = tmp_path / "tests" / "test_app.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_run(cmd, cwd=None, capture_output=True, text=True, timeout=None):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda name: "/usr/bin/pytest" if name == "pytest" else None)
    monkeypatch.setattr("gha_remediator.verification.adapters.subprocess.run", fake_run)

    report = _make_report(failure_class="test_failure", text="pytest failure", lines=["tests/test_app.py::test_ok FAILED"])
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["tests/test_app.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="tests/test_app.py", reason="error location from log")],
    )
    plan = _make_plan(commands=["pytest tests/test_app.py"], failure_class="test_failure")

    result = verify_plan(plan, repo=str(tmp_path), report=report, repo_context=repo_context)

    capability = _capability(result)
    assert result.status == "accepted"
    assert capability["selected_validator"] == "pytest_target"
    assert seen["cmd"] == ["/usr/bin/pytest", "tests/test_app.py"]


def test_pytest_target_derives_single_grounded_target(monkeypatch, tmp_path):
    src_file = tmp_path / "pkg" / "app.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("def value():\n    return 1\n", encoding="utf-8")
    test_file = tmp_path / "tests" / "test_app.py"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text("def test_value():\n    assert True\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def fake_run(cmd, cwd=None, capture_output=True, text=True, timeout=None):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda name: "/usr/bin/pytest" if name == "pytest" else None)
    monkeypatch.setattr("gha_remediator.verification.adapters.subprocess.run", fake_run)

    report = _make_report(failure_class="test_failure", text="pytest failure", lines=["pkg/app.py:1 assertion error"])
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["pkg/app.py", "tests/test_app.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="pkg/app.py", reason="error location from log")],
    )
    plan = _make_plan(failure_class="test_failure")

    result = verify_plan(plan, repo=str(tmp_path), report=report, repo_context=repo_context)

    capability = _capability(result)
    assert result.status == "accepted"
    assert capability["selected_validator"] == "pytest_target"
    assert seen["cmd"] == ["/usr/bin/pytest", "tests/test_app.py"]


def test_pytest_target_no_grounded_target_is_inconclusive(monkeypatch, tmp_path):
    src_file = tmp_path / "pkg" / "app.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("def value():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda name: "/usr/bin/pytest" if name == "pytest" else None)
    report = _make_report(failure_class="test_failure", text="pytest failure", lines=["pkg/app.py:1 assertion error"])
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["pkg/app.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="pkg/app.py", reason="error location from log")],
    )
    plan = _make_plan(failure_class="test_failure")

    result = verify_plan(plan, repo=str(tmp_path), report=report, repo_context=repo_context)

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "pytest_target"
    assert capability["availability"] == "reduced"


def test_pytest_target_multiple_grounded_targets_is_inconclusive(monkeypatch, tmp_path):
    src_file = tmp_path / "pkg" / "app.py"
    src_file.parent.mkdir(parents=True)
    src_file.write_text("def value():\n    return 1\n", encoding="utf-8")
    test_a = tmp_path / "tests" / "test_app.py"
    test_a.parent.mkdir(exist_ok=True)
    test_a.write_text("def test_a():\n    assert True\n", encoding="utf-8")
    test_b = tmp_path / "tests" / "app_test.py"
    test_b.write_text("def test_b():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda name: "/usr/bin/pytest" if name == "pytest" else None)
    report = _make_report(failure_class="test_failure", text="pytest failure", lines=["pkg/app.py:1 assertion error"])
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["pkg/app.py", "tests/test_app.py", "tests/app_test.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="pkg/app.py", reason="error location from log")],
    )
    plan = _make_plan(failure_class="test_failure")

    result = verify_plan(plan, repo=str(tmp_path), report=report, repo_context=repo_context)

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "pytest_target"


def test_pytest_target_missing_pytest_is_inconclusive(monkeypatch, tmp_path):
    test_file = tmp_path / "tests" / "test_app.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda _name: None)
    report = _make_report(failure_class="test_failure", text="pytest failure", lines=["tests/test_app.py::test_ok FAILED"])
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["tests/test_app.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="tests/test_app.py", reason="error location from log")],
    )
    plan = _make_plan(failure_class="test_failure")

    result = verify_plan(plan, repo=str(tmp_path), report=report, repo_context=repo_context)

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "pytest_target"
    assert capability["availability"] == "unavailable"


def test_adapter_timeout_is_inconclusive(monkeypatch, tmp_path):
    test_file = tmp_path / "tests" / "test_app.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=45)

    monkeypatch.setattr("gha_remediator.verification.adapters.shutil.which", lambda name: "/usr/bin/pytest" if name == "pytest" else None)
    monkeypatch.setattr("gha_remediator.verification.adapters.subprocess.run", fake_run)
    report = _make_report(failure_class="test_failure", text="pytest failure", lines=["tests/test_app.py::test_ok FAILED"])
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["tests/test_app.py"],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
        candidate_files=[RepoCandidateFile(path="tests/test_app.py", reason="error location from log")],
    )
    plan = _make_plan(failure_class="test_failure")

    result = verify_plan(plan, repo=str(tmp_path), report=report, repo_context=repo_context)

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "pytest_target"
    assert capability["summary"] == "validator pytest_target timed out"


def test_sandbox_inconclusive_result_does_not_get_accepted(monkeypatch, tmp_path):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("flask==3.0.0\n", encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", "flask==3.0.0\n", "requests==2.32.0\n")],
        fix_type="custom_fix",
    )

    from gha_remediator.verification.adapters import (
        AdapterCheckResult,
        AdapterExecutionPlan,
        AdapterSelection,
    )

    monkeypatch.setattr(
        "gha_remediator.verification.verify.select_adapter",
        lambda *args, **kwargs: AdapterSelection(
            name="generic",
            reason="forced execution plan for sandbox test",
            execution=AdapterExecutionPlan(commands=["echo verify"], workdir=".", source="adapter"),
            matching_validators=["generic"],
            suppressed_validators=[],
        ),
    )
    monkeypatch.setattr(
        "gha_remediator.verification.verify.run_adapter_check",
        lambda *args, **kwargs: AdapterCheckResult(
            status="passed",
            reason="forced adapter pass",
            execution=AdapterExecutionPlan(commands=["echo verify"], workdir=".", source="adapter"),
            summary="forced adapter pass",
        ),
    )
    monkeypatch.setattr(
        "gha_remediator.verification.verify.verify_commands_locally",
        lambda *args, **kwargs: ("inconclusive", {"reason": "local sandbox timeout"}),
    )

    result = verify_plan(plan, repo=str(tmp_path))

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["outcome"] == "inconclusive"
    assert capability["summary"] == "sandbox execution was inconclusive"


def test_node_workspace_commands_do_not_execute_as_raw_fallback(monkeypatch, tmp_path):
    package_json = tmp_path / "package.json"
    package_json.write_text('{"scripts": {"build": "vite build"}}\n', encoding="utf-8")
    repo_context = RepoContext(
        repo_root=str(tmp_path),
        tree_entries=["package.json"],
        manifests=["package.json"],
        lockfiles=[],
        workflow_files=[],
        package_scripts={"package.json": {"build": "vite build"}},
        candidate_files=[],
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("sandbox should not execute raw node commands")

    monkeypatch.setattr("gha_remediator.verification.verify.verify_commands_locally", fail_if_called)

    result = verify_plan(
        _make_plan(commands=["npm run build"]),
        repo=str(tmp_path),
        repo_context=repo_context,
    )

    capability = _capability(result)
    assert result.status == "inconclusive"
    assert capability["selected_validator"] == "node_workspace"
    assert capability["summary"] == "no narrow deterministic validator exists for the Node workspace commands"


def test_replay_skipped_evidence_is_structured(tmp_path):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("flask==3.0.0\n", encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", "flask==3.0.0\n", "requests==2.32.0\n")],
    )

    result = verify_plan(plan, repo=str(tmp_path))

    replay = result.evidence["replay"]
    capability = _capability(result)
    assert result.status == "accepted"
    assert replay["classification"] == "skipped"
    assert replay["attempted"] is False
    assert capability["selected_validator"] == "python_dependency_manifest"


def test_replay_failed_evidence_is_structured(monkeypatch, tmp_path):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("flask==3.0.0\n", encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", "flask==3.0.0\n", "requests==2.32.0\n")],
        fix_type="python_add_dependency",
    )

    def fake_replay_with_act(repo, cfg):
        return "failed", {
            "attempted": True,
            "tool_available": True,
            "cmd": ["act", "push"],
            "job": None,
            "event": "push",
            "workdir": repo,
            "returncode": 1,
            "classification": "failed",
            "stdout_tail": "failure",
            "stderr_tail": "error",
        }

    monkeypatch.setattr("gha_remediator.verification.verify.replay_with_act", fake_replay_with_act)

    result = verify_plan(plan, repo=str(tmp_path), replay_cfg=ReplayConfig())

    capability = _capability(result)
    replay = result.evidence["replay"]
    assert result.status == "failed_replay"
    assert replay["classification"] == "failed"
    assert capability["selected_validator"] == "python_dependency_manifest"
    assert capability["execution_mode"] == "replay"
    assert capability["summary"] == "deterministic validation passed, but replay failed"
