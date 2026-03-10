import pytest

from gha_remediator.ingestion import github_actions as gha


def test_parse_repo_valid():
    owner, name = gha._parse_repo("octocat/hello-world")
    assert owner == "octocat"
    assert name == "hello-world"


@pytest.mark.parametrize("repo", ["octocat", "/hello", "octocat/", ""])
def test_parse_repo_invalid(repo):
    with pytest.raises(ValueError):
        gha._parse_repo(repo)


def test_load_logs_with_explicit_run_id(monkeypatch):
    monkeypatch.setattr(gha, "_session", lambda token: object())
    monkeypatch.setattr(
        gha,
        "_run_by_id",
        lambda s, owner, name, run_id: {
            "id": run_id,
            "run_number": 12,
            "run_attempt": 1,
            "event": "push",
            "name": "CI",
            "html_url": "https://github.com/octocat/hello-world/actions/runs/123",
        },
    )
    monkeypatch.setattr(
        gha,
        "_download_run_logs",
        lambda s, owner, name, run_id: [("job_1.txt", "log line 1"), ("job_2.txt", "log line 2")],
    )

    out = gha.load_github_actions_logs("octocat/hello-world", run_id=123, token="x")

    assert len(out) == 2
    assert out[0]["source"] == "github_actions"
    assert out[0]["ground_truth"] is None
    assert out[0]["metadata"]["run_id"] == 123
    assert "github/octocat/hello-world/runs/123/" in out[0]["path"]


def test_load_logs_uses_failed_runs_when_run_id_missing(monkeypatch):
    monkeypatch.setattr(gha, "_session", lambda token: object())
    monkeypatch.setattr(
        gha,
        "_failed_runs",
        lambda s, owner, name, limit: [{"id": 101, "name": "CI"}, {"id": 202, "name": "CI"}][:limit],
    )
    monkeypatch.setattr(
        gha,
        "_download_run_logs",
        lambda s, owner, name, run_id: [(f"{run_id}.txt", f"log for {run_id}")],
    )

    out = gha.load_github_actions_logs("octocat/hello-world", limit=2, token="x")
    run_ids = [entry["metadata"]["run_id"] for entry in out]
    assert run_ids == [101, 202]


def test_load_logs_with_artifacts(monkeypatch):
    monkeypatch.setattr(gha, "_session", lambda token: object())
    monkeypatch.setattr(gha, "_run_by_id", lambda s, owner, name, run_id: {"id": run_id, "name": "CI"})
    monkeypatch.setattr(gha, "_download_run_logs", lambda s, owner, name, run_id: [("job.txt", "log")])
    monkeypatch.setattr(
        gha,
        "_download_artifacts_for_run",
        lambda s, owner, name, run_id, out_dir: [f"{out_dir}/run_{run_id}_artifact.zip"],
    )

    out = gha.load_github_actions_logs(
        "octocat/hello-world",
        run_id=77,
        token="x",
        include_artifacts=True,
        artifact_dir="tmp_artifacts",
    )

    assert len(out) == 1
    assert out[0]["metadata"]["artifact_paths"] == ["tmp_artifacts/run_77_artifact.zip"]


def test_load_logs_rejects_bad_limit():
    with pytest.raises(ValueError):
        gha.load_github_actions_logs("octocat/hello-world", limit=0, token="x")
