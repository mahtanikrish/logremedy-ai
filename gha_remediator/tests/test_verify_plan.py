from __future__ import annotations

from difflib import unified_diff
from pathlib import Path

from gha_remediator.types import Patch, RemediationPlan
from gha_remediator.verification.replay import ReplayConfig
from gha_remediator.verification.verify import verify_plan


def _make_plan(
    *,
    patches: list[Patch] | None = None,
    commands: list[str] | None = None,
    fix_type: str = "custom_fix",
) -> RemediationPlan:
    return RemediationPlan(
        failure_class="environment_dependency_failure",
        fix_type=fix_type,
        patches=patches or [],
        commands=commands or [],
        assumptions=[],
        rollback=[],
        risk_level="low",
        evidence={},
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


def test_static_validation_uses_patched_copy_and_records_ordered_gates(tmp_path):
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    workflow_path = workflow_dir / "ci.yml"
    original = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: []\n"
    broken = "on: push\njobs:\n  build:\n    runs-on: ubuntu-latest\n    steps: [\n"
    workflow_path.write_text(original, encoding="utf-8")

    plan = _make_plan(
        patches=[_modify_patch(".github/workflows/ci.yml", original, broken)],
    )

    result = verify_plan(plan, repo=str(tmp_path))

    assert result.status == "rejected_static"
    assert result.reason.startswith("static validation failed:")
    assert result.evidence["gate"] == "static"
    assert [gate["name"] for gate in result.evidence["gates"]] == [
        "preconditions",
        "policy",
        "patch_apply",
        "static",
        "sandbox",
        "replay",
    ]
    assert result.evidence["gates"][0]["status"] == "passed"
    assert result.evidence["gates"][3]["status"] == "failed"
    assert result.evidence["gates"][4]["status"] == "skipped"
    assert result.evidence["static"]["checks"][0]["ok"] is False
    assert workflow_path.read_text(encoding="utf-8") == original


def test_add_file_patch_no_longer_fails_old_existence_precondition(tmp_path):
    (tmp_path / "README.md").write_text("# repo\n", encoding="utf-8")
    plan = _make_plan(
        patches=[_add_file_patch("requirements.txt", "requests==2.32.0\n")],
    )

    result = verify_plan(plan, repo=str(tmp_path))

    assert result.status == "inconclusive"
    assert result.evidence["gate"] == "replay"
    patch_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "patch_apply")
    replay_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "replay")
    assert patch_gate["status"] == "passed"
    assert replay_gate["status"] == "skipped"
    assert not (tmp_path / "requirements.txt").exists()


def test_invalid_patch_fails_at_patch_apply(tmp_path):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("flask==3.0.0\n", encoding="utf-8")
    invalid_diff = (
        "--- requirements.txt\n"
        "+++ requirements.txt\n"
        "@@ -1 +1 @@\n"
        "-requests==2.32.0\n"
        "+flask==3.0.0\n"
    )
    plan = _make_plan(patches=[Patch(path="requirements.txt", diff=invalid_diff)])

    result = verify_plan(plan, repo=str(tmp_path))

    assert result.status == "rejected_precondition"
    assert result.evidence["gate"] == "patch_apply"
    patch_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "patch_apply")
    assert patch_gate["status"] == "failed"
    assert patch_gate["details"]["path"] == "requirements.txt"
    assert req_path.read_text(encoding="utf-8") == "flask==3.0.0\n"


def test_sandbox_runs_against_patched_workspace(monkeypatch, tmp_path):
    config_path = tmp_path / "requirements.txt"
    config_path.write_text("flask==3.0.0\n", encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", "flask==3.0.0\n", "requests==2.32.0\n")],
        commands=["echo sandbox"],
    )

    seen: dict[str, str] = {}

    def fake_verify_commands_locally(commands, repo, timeout_s=30):
        seen["repo"] = repo
        seen["content"] = Path(repo, "requirements.txt").read_text(encoding="utf-8")
        return "verified", {"commands": commands}

    monkeypatch.setattr("gha_remediator.verification.verify.verify_commands_locally", fake_verify_commands_locally)

    result = verify_plan(plan, repo=str(tmp_path))

    assert result.status == "inconclusive"
    assert seen["repo"] != str(tmp_path)
    assert seen["content"] == "requests==2.32.0\n"
    assert config_path.read_text(encoding="utf-8") == "flask==3.0.0\n"


def test_replay_runs_against_patched_workspace(monkeypatch, tmp_path):
    req_path = tmp_path / "requirements.txt"
    req_path.write_text("flask==3.0.0\n", encoding="utf-8")
    plan = _make_plan(
        patches=[_modify_patch("requirements.txt", "flask==3.0.0\n", "requests==2.32.0\n")],
    )

    seen: dict[str, str] = {}

    def fake_replay_with_act(repo, cfg):
        seen["repo"] = repo
        seen["content"] = Path(repo, "requirements.txt").read_text(encoding="utf-8")
        return "verified", {"cmd": ["act", "push"], "returncode": 0}

    monkeypatch.setattr("gha_remediator.verification.verify.replay_with_act", fake_replay_with_act)

    result = verify_plan(plan, repo=str(tmp_path), replay_cfg=ReplayConfig())

    assert result.status == "verified"
    assert result.evidence["gate"] == "replay"
    assert seen["repo"] != str(tmp_path)
    assert seen["content"] == "requests==2.32.0\n"
    assert req_path.read_text(encoding="utf-8") == "flask==3.0.0\n"


def test_command_only_plan_skips_replay_even_when_configured(monkeypatch, tmp_path):
    (tmp_path / "README.md").write_text("# repo\n", encoding="utf-8")
    plan = _make_plan(commands=["echo sandbox"], fix_type="shell_only_fix")

    def fake_verify_commands_locally(commands, repo, timeout_s=30):
        return "verified", {"commands": commands}

    def fail_if_called(repo, cfg):
        raise AssertionError("replay should not run for command-only plans")

    monkeypatch.setattr("gha_remediator.verification.verify.verify_commands_locally", fake_verify_commands_locally)
    monkeypatch.setattr("gha_remediator.verification.verify.replay_with_act", fail_if_called)

    result = verify_plan(plan, repo=str(tmp_path), replay_cfg=ReplayConfig())

    assert result.status == "inconclusive"
    assert result.reason == "replay skipped: no persistent patched repo state"
    sandbox_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "sandbox")
    replay_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "replay")
    assert sandbox_gate["status"] == "passed"
    assert replay_gate["status"] == "skipped"


def test_benchmark_profile_allows_existing_python_patch_and_runs_static(tmp_path):
    cfg_dir = tmp_path / "docs" / "source"
    cfg_dir.mkdir(parents=True)
    original_path = cfg_dir / "conf.py"
    original = "project = 'demo'\n"
    updated = "project = 'demo'\nhtml_title = 'Demo'\n"
    original_path.write_text(original, encoding="utf-8")

    plan = _make_plan(
        patches=[_modify_patch("docs/source/conf.py", original, updated)],
    )

    result = verify_plan(
        plan,
        repo=str(tmp_path),
        verification_profile="benchmark_supported_files",
    )

    assert result.status == "inconclusive"
    policy_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "policy")
    static_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "static")
    assert policy_gate["status"] == "passed"
    assert static_gate["status"] == "passed"
    assert result.evidence["static"]["checks"][0]["type"] == "python_compile"


def test_benchmark_profile_rejects_missing_python_target(tmp_path):
    plan = _make_plan(
        patches=[_add_file_patch("docs/source/conf.py", "project = 'demo'\n")],
    )

    result = verify_plan(
        plan,
        repo=str(tmp_path),
        verification_profile="benchmark_supported_files",
    )

    assert result.status == "rejected_policy"
    assert "existing file" in result.reason


def test_benchmark_profile_rejects_large_python_patch_budget(tmp_path):
    target_dir = tmp_path / "docs" / "source"
    target_dir.mkdir(parents=True)
    target_path = target_dir / "conf.py"
    before_lines = [f"value_{idx} = {idx}\n" for idx in range(100)]
    after_lines = [f"value_{idx} = {idx + 1}\n" for idx in range(100)]
    before = "".join(before_lines)
    after = "".join(after_lines)
    target_path.write_text(before, encoding="utf-8")

    plan = _make_plan(
        patches=[_modify_patch("docs/source/conf.py", before, after)],
    )

    result = verify_plan(
        plan,
        repo=str(tmp_path),
        verification_profile="benchmark_supported_files",
    )

    assert result.status == "rejected_policy"
    assert "patch diff too large" in result.reason


def test_benchmark_profile_accepts_git_style_diff_for_existing_python_file(tmp_path):
    cfg_dir = tmp_path / "timeseries"
    cfg_dir.mkdir(parents=True)
    target_path = cfg_dir / "setup.py"
    before = "value = 1\n"
    after = "value = 2\n"
    target_path.write_text(before, encoding="utf-8")
    diff = (
        "diff --git a/timeseries/setup.py b/timeseries/setup.py\n"
        "index 1111111..2222222 100644\n"
        "--- a/timeseries/setup.py\n"
        "+++ b/timeseries/setup.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )
    plan = _make_plan(
        patches=[Patch(path="timeseries/setup.py", diff=diff)],
    )

    result = verify_plan(
        plan,
        repo=str(tmp_path),
        verification_profile="benchmark_supported_files",
    )

    assert result.status == "inconclusive"
    patch_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "patch_apply")
    static_gate = next(gate for gate in result.evidence["gates"] if gate["name"] == "static")
    assert patch_gate["status"] == "passed"
    assert static_gate["status"] == "passed"
