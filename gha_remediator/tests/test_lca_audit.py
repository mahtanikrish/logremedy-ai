from gha_remediator.evaluation.lca_audit import audit_case, summarize_audit_cases


def test_audit_case_flags_policy_and_services():
    row = {
        "id": 42,
        "repo_owner": "example",
        "repo_name": "demo",
        "workflow_path": ".github/workflows/ci.yml",
        "sha_fail": "abc",
        "sha_success": "def",
        "difficulty": 1,
        "workflow": """
name: CI
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:14
""",
        "logs": [
            {
                "step_name": "test/1_step.txt",
                "log": "line one\nline two\n##[error]Process completed with exit code 1.",
            }
        ],
        "diff": """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old
+new
""",
        "changed_files": ["src/app.py"],
    }

    case = audit_case(row, config="default")
    assert case.repo == "example/demo"
    assert case.uses_services is True
    assert case.all_changed_files_allowed_now is False
    assert case.verification_readiness_now == "blocked_by_policy"
    assert "gold diff is blocked by current patch policy" in case.notes


def test_audit_case_marks_workflow_only_case_static_ready():
    row = {
        "id": 7,
        "repo_owner": "example",
        "repo_name": "workflow-repo",
        "workflow_path": ".github/workflows/release.yml",
        "sha_fail": "abc",
        "sha_success": "def",
        "difficulty": 0,
        "workflow": """
name: Release
jobs:
  build:
    runs-on: ubuntu-latest
""",
        "logs": [{"step_name": "build/1.txt", "log": "bad yaml"}],
        "diff": """diff --git a/.github/workflows/release.yml b/.github/workflows/release.yml
--- a/.github/workflows/release.yml
+++ b/.github/workflows/release.yml
@@ -1 +1 @@
-bad
+good
""",
        "changed_files": [".github/workflows/release.yml"],
    }

    case = audit_case(row, config="default")
    assert case.all_changed_files_allowed_now is True
    assert case.static_checks_applicable_now is True
    assert case.change_surface == "workflow_only"


def test_summarize_audit_cases_counts_candidates():
    first = audit_case(
        {
            "id": 1,
            "repo_owner": "a",
            "repo_name": "one",
            "workflow_path": ".github/workflows/ci.yml",
            "sha_fail": "abc",
            "sha_success": "def",
            "difficulty": 0,
            "workflow": "jobs:\n  test:\n    runs-on: ubuntu-latest\n",
            "logs": [{"step_name": "x", "log": "error"}],
            "diff": "",
            "changed_files": [".github/workflows/ci.yml"],
        },
        config="default",
    )
    second = audit_case(
        {
            "id": 2,
            "repo_owner": "a",
            "repo_name": "two",
            "workflow_path": ".github/workflows/ci.yml",
            "sha_fail": "abc",
            "sha_success": "def",
            "difficulty": 2,
            "workflow": "jobs:\n  test:\n    runs-on: windows-latest\n",
            "logs": [{"step_name": "x", "log": "error\nmore"}],
            "diff": "",
            "changed_files": ["src/app.py"],
        },
        config="default",
    )

    summary = summarize_audit_cases([first, second], top_n=2)
    assert summary["rows"] == 2
    assert summary["unique_repos"] == 2
    assert summary["all_changed_files_allowed_now"] == 1
    assert len(summary["top_component_candidates"]) == 2
