#!/usr/bin/env python3
"""Materialize repo snapshots for an LCA-backed benchmark split.

This script keeps the benchmark repo lightweight. It creates:
- a shared bare mirror cache per upstream repository
- a detached working snapshot per incident at the failing SHA
- a repo-map JSON file consumable by `gha_remediator eval-benchmark`

It operates from benchmark incident metadata, so it does not require the
original parquet dataset at runtime once the incidents already exist.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark-root", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--partition", choices=["train", "dev", "test", "all"], default="dev")
    parser.add_argument(
        "--cache-root",
        required=True,
        help="Root directory for mirrors and per-incident snapshots.",
    )
    parser.add_argument(
        "--out-repo-map",
        required=True,
        help="Output JSON repo-map for eval-benchmark --repo-map.",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Delete and recreate existing incident snapshots.",
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Fetch updates into existing mirrors before creating snapshots.",
    )
    return parser.parse_args()


def _resolve_path(root: Path, maybe_relative: str) -> Path:
    candidate = Path(maybe_relative).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def _load_split_ids(split_path: Path, partition: str) -> list[str]:
    payload = json.loads(split_path.read_text(encoding="utf-8"))
    if partition == "all":
        return list(payload.get("train", [])) + list(payload.get("dev", [])) + list(payload.get("test", []))
    return list(payload.get(partition, []))


def _load_incident_metadata(benchmark_root: Path, incident_id: str) -> dict:
    metadata_path = benchmark_root / "incidents" / incident_id / "metadata.json"
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _repo_url(metadata: dict) -> str:
    repo_url = metadata.get("repo_url")
    if isinstance(repo_url, str) and repo_url.strip():
        return repo_url.strip()
    repo = str(metadata.get("repo", "")).strip()
    if not repo or "/" not in repo:
        raise ValueError(f"Cannot resolve repo URL from metadata: {metadata}")
    return f"https://github.com/{repo}.git"


def _repo_slug(metadata: dict) -> str:
    repo = str(metadata.get("repo", "")).strip()
    if repo:
        return repo.replace("/", "__")
    repo_url = _repo_url(metadata)
    cleaned = repo_url.removeprefix("https://").removeprefix("http://").removeprefix("git@")
    cleaned = cleaned.replace("github.com:", "").replace("github.com/", "")
    cleaned = cleaned.removesuffix(".git")
    return cleaned.replace("/", "__")


def _run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        details = stderr or stdout or str(exc)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{details}") from exc


def _ensure_mirror(repo_url: str, mirror_dir: Path, *, fetch: bool) -> None:
    if not mirror_dir.exists():
        mirror_dir.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--mirror", repo_url, str(mirror_dir)])
        return
    if fetch:
        _run(["git", "remote", "update", "--prune"], cwd=mirror_dir)


def _mirror_has_commit(mirror_dir: Path, sha_fail: str) -> bool:
    try:
        _run(["git", "--git-dir", str(mirror_dir), "rev-parse", "--verify", f"{sha_fail}^{{commit}}"])
        return True
    except RuntimeError:
        return False


def _ensure_commit_available(mirror_dir: Path, repo_url: str, sha_fail: str) -> None:
    if _mirror_has_commit(mirror_dir, sha_fail):
        return
    _run(["git", "--git-dir", str(mirror_dir), "fetch", repo_url, sha_fail])
    if _mirror_has_commit(mirror_dir, sha_fail):
        return
    _run(["git", "--git-dir", str(mirror_dir), "remote", "update", "--prune"])
    if not _mirror_has_commit(mirror_dir, sha_fail):
        raise RuntimeError(
            f"Required commit {sha_fail} is not available in mirror {mirror_dir} even after fetch."
        )


def _snapshot_is_ready(snapshot_dir: Path, sha_fail: str) -> bool:
    if not snapshot_dir.exists():
        return False
    try:
        head = _run(["git", "rev-parse", "HEAD"], cwd=snapshot_dir).stdout.strip()
    except subprocess.CalledProcessError:
        return False
    return head == sha_fail


def _create_snapshot(mirror_dir: Path, snapshot_dir: Path, sha_fail: str, *, refresh: bool) -> None:
    if snapshot_dir.exists() and refresh:
        shutil.rmtree(snapshot_dir)

    if _snapshot_is_ready(snapshot_dir, sha_fail):
        return

    if snapshot_dir.exists():
        shutil.rmtree(snapshot_dir)

    snapshot_dir.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "--git-dir", str(mirror_dir), "worktree", "add", "--detach", str(snapshot_dir), sha_fail])


def main() -> int:
    args = parse_args()

    benchmark_root = Path(args.benchmark_root).expanduser().resolve()
    split_path = _resolve_path(benchmark_root, args.split)
    cache_root = Path(args.cache_root).expanduser().resolve()
    mirrors_root = cache_root / "mirrors"
    snapshots_root = cache_root / "snapshots"

    incident_ids = _load_split_ids(split_path, args.partition)
    if args.limit is not None:
        incident_ids = incident_ids[: args.limit]

    repo_map: dict[str, str] = {}
    manifest_rows: list[dict] = []

    for incident_id in incident_ids:
        metadata = _load_incident_metadata(benchmark_root, incident_id)
        repo_url = _repo_url(metadata)
        repo_slug = _repo_slug(metadata)
        sha_fail = str(metadata.get("sha_fail", "")).strip()
        source_case_id = str(metadata.get("source_case_id", "")).strip() or None
        repo_name = str(metadata.get("repo", "")).strip() or None
        if not sha_fail:
            raise ValueError(f"{incident_id} is missing sha_fail in metadata.")

        mirror_dir = mirrors_root / f"{repo_slug}.git"
        snapshot_dir = snapshots_root / f"{incident_id}__{repo_slug}__{sha_fail[:12]}"

        _ensure_mirror(repo_url, mirror_dir, fetch=args.fetch)
        _ensure_commit_available(mirror_dir, repo_url, sha_fail)
        _create_snapshot(mirror_dir, snapshot_dir, sha_fail, refresh=args.refresh)

        repo_map[incident_id] = str(snapshot_dir)
        if source_case_id:
            repo_map[source_case_id] = str(snapshot_dir)
        if repo_name:
            repo_map[repo_name] = str(snapshot_dir)

        manifest_rows.append(
            {
                "incident_id": incident_id,
                "source_case_id": source_case_id,
                "repo": repo_name,
                "repo_url": repo_url,
                "sha_fail": sha_fail,
                "mirror_dir": str(mirror_dir),
                "snapshot_dir": str(snapshot_dir),
            }
        )

    out_repo_map = Path(args.out_repo_map).expanduser().resolve()
    out_repo_map.parent.mkdir(parents=True, exist_ok=True)
    out_repo_map.write_text(json.dumps(repo_map, indent=2) + "\n", encoding="utf-8")

    summary = {
        "benchmark_root": str(benchmark_root),
        "split": str(split_path),
        "partition": args.partition,
        "cache_root": str(cache_root),
        "out_repo_map": str(out_repo_map),
        "num_incidents": len(incident_ids),
        "materialized": manifest_rows,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
