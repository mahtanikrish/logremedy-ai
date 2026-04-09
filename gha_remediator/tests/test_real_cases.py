import json

from gha_remediator.evaluation.real_cases import export_real_case_stub


def test_export_real_case_stub_writes_log_and_annotation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "gha_remediator.evaluation.real_cases.load_github_actions_logs",
        lambda repo, run_id: [
            {
                "path": f"github/{repo}/runs/{run_id}/0_build.txt",
                "content": "line 1\nline 2",
                "metadata": {
                    "workflow_name": "CI",
                    "html_url": "https://github.com/example/repo/actions/runs/123",
                },
            }
        ],
    )

    out = export_real_case_stub(
        repo="example/repo",
        run_id=123,
        out_dir=str(tmp_path),
    )

    annotation = json.loads((tmp_path / "example_repo_123.json").read_text(encoding="utf-8"))
    log_text = (tmp_path / "example_repo_123.log").read_text(encoding="utf-8")

    assert out["annotation_path"].endswith("example_repo_123.json")
    assert out["log_path"].endswith("example_repo_123.log")
    assert annotation["case_id"] == "example_repo_123"
    assert annotation["workflow_name"] == "CI"
    assert "===== github/example/repo/runs/123/0_build.txt =====" in log_text
