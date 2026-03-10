from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

GITHUB_API = "https://api.github.com"


def _parse_repo(repo: str) -> Tuple[str, str]:
    parts = repo.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError("repo must be in the format 'owner/name'")
    return parts[0], parts[1]


def _session(token: Optional[str]) -> requests.Session:
    tok = token or os.environ.get("GITHUB_TOKEN")
    if not tok:
        raise RuntimeError("GITHUB_TOKEN not set")

    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def _get_json(session: requests.Session, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = session.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def _get_bytes(session: requests.Session, url: str) -> bytes:
    r = session.get(url, timeout=120, allow_redirects=True)
    r.raise_for_status()
    return r.content


def _extract_logs(zip_blob: bytes) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(zip_blob)) as zf:
        for info in sorted(zf.infolist(), key=lambda x: x.filename):
            if info.is_dir():
                continue
            with zf.open(info) as f:
                text = f.read().decode("utf-8", errors="replace")
            out.append((info.filename, text))
    return out


def _failed_runs(
    session: requests.Session,
    owner: str,
    name: str,
    per_page: int,
) -> List[Dict[str, Any]]:
    per_page = min(max(per_page, 1), 100)
    url = f"{GITHUB_API}/repos/{owner}/{name}/actions/runs"
    data = _get_json(
        session,
        url,
        params={
            "status": "completed",
            "conclusion": "failure",
            "per_page": per_page,
        },
    )
    return list(data.get("workflow_runs", []))


def _run_by_id(session: requests.Session, owner: str, name: str, run_id: int) -> Dict[str, Any]:
    url = f"{GITHUB_API}/repos/{owner}/{name}/actions/runs/{run_id}"
    return _get_json(session, url)


def _download_run_logs(session: requests.Session, owner: str, name: str, run_id: int) -> List[Tuple[str, str]]:
    url = f"{GITHUB_API}/repos/{owner}/{name}/actions/runs/{run_id}/logs"
    return _extract_logs(_get_bytes(session, url))


def _download_artifacts_for_run(
    session: requests.Session,
    owner: str,
    name: str,
    run_id: int,
    out_dir: str,
) -> List[str]:
    url = f"{GITHUB_API}/repos/{owner}/{name}/actions/runs/{run_id}/artifacts"
    data = _get_json(session, url, params={"per_page": 100})
    artifacts = data.get("artifacts", [])
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    paths: List[str] = []
    for art in artifacts:
        artifact_id = art.get("id")
        artifact_name = art.get("name", "artifact")
        if artifact_id is None:
            continue
        blob = _get_bytes(
            session,
            f"{GITHUB_API}/repos/{owner}/{name}/actions/artifacts/{artifact_id}/zip",
        )
        output_path = out_root / f"run_{run_id}_{artifact_name}_{artifact_id}.zip"
        output_path.write_bytes(blob)
        paths.append(str(output_path))
    return paths


def load_github_actions_logs(
    repo: str,
    run_id: Optional[int] = None,
    limit: int = 1,
    token: Optional[str] = None,
    include_artifacts: bool = False,
    artifact_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Load failed GitHub Actions run logs and normalize to synthetic-loader style.

    Each entry has:
      {
        "path": str,
        "content": str,
        "source": "github_actions",
        "ground_truth": None,
        "metadata": {...}
      }
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")

    owner, name = _parse_repo(repo)
    s = _session(token)

    runs: List[Dict[str, Any]]
    if run_id is not None:
        runs = [_run_by_id(s, owner, name, run_id)]
    else:
        per_page = min(max(limit * 5, 20), 100)
        runs = _failed_runs(s, owner, name, per_page)

    normalized: List[Dict[str, Any]] = []
    for run in runs:
        if len(normalized) >= limit:
            break
        rid = int(run["id"])
        try:
            logs = _download_run_logs(s, owner, name, rid)
        except requests.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 410 and run_id is None:
                continue
            if status == 410 and run_id is not None:
                raise RuntimeError(f"Logs for run_id={rid} are no longer available (HTTP 410 Gone).") from e
            raise

        artifact_paths: List[str] = []
        if include_artifacts:
            out_dir = artifact_dir or f"artifacts/run_{rid}"
            artifact_paths = _download_artifacts_for_run(s, owner, name, rid, out_dir)

        for member_name, content in logs:
            normalized.append(
                {
                    "path": f"github/{owner}/{name}/runs/{rid}/{member_name}",
                    "content": content,
                    "source": "github_actions",
                    "ground_truth": None,
                    "metadata": {
                        "repo": f"{owner}/{name}",
                        "run_id": rid,
                        "run_number": run.get("run_number"),
                        "run_attempt": run.get("run_attempt"),
                        "event": run.get("event"),
                        "workflow_name": run.get("name"),
                        "html_url": run.get("html_url"),
                        "artifact_paths": artifact_paths,
                    },
                }
            )

    if run_id is None and not normalized:
        raise RuntimeError(
            "No failed runs with downloadable logs were found. "
            "Recent failed runs may have expired logs (HTTP 410)."
        )

    return normalized
