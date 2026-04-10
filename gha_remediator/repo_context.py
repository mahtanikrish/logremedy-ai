from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Sequence
import json
import os
import re
import tomllib

from .types import RCAReport, RepoCandidateFile, RepoContext, RepoSnippet


MANIFEST_BASENAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Pipfile",
    "setup.py",
    "setup.cfg",
    "poetry.lock",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "composer.json",
}

LOCKFILE_BASENAMES = {
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Pipfile.lock",
    "poetry.lock",
    "Cargo.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
}

TEXT_SNIPPET_SUFFIXES = {
    ".c",
    ".cc",
    ".cfg",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".gradle",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

RESOLVABLE_IMPORT_SUFFIXES = (
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".json",
)

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".next",
    ".nuxt",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "coverage",
    "node_modules",
}

MAX_SCANNED_FILES = 4000
MAX_SNIPPET_BYTES = 48_000
MAX_SNIPPET_LINES = 24

_PY_TRACEBACK_RE = re.compile(r'File ["\'](?P<path>[^"\']+)["\'], line (?P<line>\d+)')
_LINE_COL_RE = re.compile(
    r"(?P<path>[A-Za-z0-9_./-]+\.(?:py|js|jsx|ts|tsx|json|ya?ml|toml|cfg|ini|sh))"
    r"(?:\(|:)(?P<line>\d+)(?:[:,](?P<col>\d+))?\)?"
)
_GENERIC_PATH_RE = re.compile(
    r"(?<![\w./-])(?P<path>(?:\.{1,2}/)?[A-Za-z0-9_./-]+(?:/[A-Za-z0-9_./-]+)*"
    r"\.(?:py|js|jsx|ts|tsx|json|ya?ml|toml|cfg|ini|sh))(?![\w.-])"
)
_IMPORT_FROM_SOURCE_RE = re.compile(
    r"Cannot find module ['\"](?P<import>[^'\"]+)['\"] from ['\"](?P<source>[^'\"]+)['\"]",
    re.IGNORECASE,
)
_TS_IMPORT_ERROR_RE = re.compile(
    r"(?P<source>[A-Za-z0-9_./-]+\.(?:ts|tsx|js|jsx))\((?P<line>\d+),(?P<col>\d+)\):"
    r".*?Cannot find module ['\"](?P<import>[^'\"]+)['\"]",
    re.IGNORECASE,
)
_SETUP_TOOL_VERSION_PATTERNS = {
    "python": re.compile(
        r"actions/setup-python@[^\n]*\n(?:(?:[^\n]*\n){0,6})?[^\n]*python-version:\s*[\"']?([^\"'\n#]+)",
        re.IGNORECASE,
    ),
    "node": re.compile(
        r"actions/setup-node@[^\n]*\n(?:(?:[^\n]*\n){0,6})?[^\n]*node-version:\s*[\"']?([^\"'\n#]+)",
        re.IGNORECASE,
    ),
    "java": re.compile(
        r"actions/setup-java@[^\n]*\n(?:(?:[^\n]*\n){0,6})?[^\n]*java-version:\s*[\"']?([^\"'\n#]+)",
        re.IGNORECASE,
    ),
    "ruby": re.compile(
        r"ruby/setup-ruby@[^\n]*\n(?:(?:[^\n]*\n){0,6})?[^\n]*ruby-version:\s*[\"']?([^\"'\n#]+)",
        re.IGNORECASE,
    ),
}


def build_repo_context(repo: Optional[str], raw_log_text: str, report: RCAReport) -> RepoContext:
    if repo is None or not str(repo).strip():
        return RepoContext(
            repo_root="",
            tree_entries=[],
            manifests=[],
            lockfiles=[],
            workflow_files=[],
            metadata={"scan_error": "repo not provided", "repo_provided": False},
        )

    root = Path(repo).expanduser().resolve()
    empty = RepoContext(
        repo_root=str(root),
        tree_entries=[],
        manifests=[],
        lockfiles=[],
        workflow_files=[],
    )

    if not root.exists() or not root.is_dir():
        empty.metadata["scan_error"] = f"repo does not exist: {root}"
        return empty

    repo_files, scan_meta = _scan_repo_files(root)
    repo_files_set = set(repo_files)

    manifests = [path for path in repo_files if Path(path).name in MANIFEST_BASENAMES]
    lockfiles = [path for path in repo_files if Path(path).name in LOCKFILE_BASENAMES]
    workflow_files = [
        path
        for path in repo_files
        if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))
    ]
    package_scripts, package_managers = _extract_package_json_details(root, manifests)
    tool_versions = _extract_tool_versions(root, workflow_files, manifests, package_managers)
    candidate_files = _extract_candidate_files(raw_log_text, repo_files_set)
    tree_entries = _build_tree_sample(repo_files, manifests, lockfiles, workflow_files, candidate_files)
    snippets = _select_snippets(
        root=root,
        report=report,
        candidate_files=candidate_files,
        manifests=manifests,
        lockfiles=lockfiles,
        workflow_files=workflow_files,
    )

    return RepoContext(
        repo_root=str(root),
        tree_entries=tree_entries,
        manifests=manifests,
        lockfiles=lockfiles,
        workflow_files=workflow_files,
        package_scripts=package_scripts,
        package_managers=package_managers,
        tool_versions=tool_versions,
        candidate_files=candidate_files,
        snippets=snippets,
        metadata=scan_meta,
    )


def format_repo_context(repo_context: RepoContext, max_chars: int = 8_000) -> str:
    repo_root = repo_context.repo_root or "(not provided)"
    sections: List[str] = [f"Repo root: {repo_root}"]

    if repo_context.metadata.get("scan_error"):
        sections.append(f"Scan error: {repo_context.metadata['scan_error']}")

    if repo_context.tree_entries:
        sections.append("Repo tree sample:\n" + "\n".join(f"- {entry}" for entry in repo_context.tree_entries[:25]))
    if repo_context.manifests:
        sections.append("Detected manifests:\n" + "\n".join(f"- {path}" for path in repo_context.manifests[:12]))
    else:
        sections.append("Detected manifests: none")
    if repo_context.lockfiles:
        sections.append("Detected lockfiles:\n" + "\n".join(f"- {path}" for path in repo_context.lockfiles[:12]))
    else:
        sections.append("Detected lockfiles: none")
    if repo_context.workflow_files:
        sections.append("Workflow files:\n" + "\n".join(f"- {path}" for path in repo_context.workflow_files[:8]))
    else:
        sections.append("Workflow files: none")
    if repo_context.package_managers:
        sections.append(
            "Package managers:\n"
            + "\n".join(
                f"- {path}: {manager}" for path, manager in sorted(repo_context.package_managers.items())[:8]
            )
        )
    if repo_context.package_scripts:
        script_lines: List[str] = []
        for path, scripts in sorted(repo_context.package_scripts.items())[:6]:
            selected = list(scripts.items())[:6]
            if selected:
                rendered = "; ".join(f"{name}={cmd}" for name, cmd in selected)
                script_lines.append(f"- {path}: {rendered}")
        if script_lines:
            sections.append("Package scripts:\n" + "\n".join(script_lines))
    if repo_context.tool_versions:
        sections.append(
            "Tool versions:\n"
            + "\n".join(
                f"- {tool}: {', '.join(values[:4])}"
                for tool, values in sorted(repo_context.tool_versions.items())
                if values
            )
        )
    if repo_context.candidate_files:
        sections.append(
            "Candidate target files from logs:\n"
            + "\n".join(
                f"- {candidate.path}: {candidate.reason}"
                for candidate in repo_context.candidate_files[:8]
            )
        )
    if repo_context.snippets:
        snippet_parts: List[str] = []
        for snippet in repo_context.snippets[:5]:
            snippet_parts.append(
                f"--- {snippet.path} [{snippet.reason}] ---\n{snippet.content}"
            )
        sections.append("Relevant repo snippets:\n" + "\n\n".join(snippet_parts))

    out_parts: List[str] = []
    total = 0
    for section in sections:
        if total + len(section) > max_chars:
            break
        out_parts.append(section)
        total += len(section) + 2
    return "\n\n".join(out_parts)


def detect_primary_package_manager(repo_context: Optional[RepoContext]) -> Optional[str]:
    if repo_context is None:
        return None
    managers = repo_context.package_managers.values()
    if any(manager == "pnpm" for manager in managers):
        return "pnpm"
    if any(manager == "yarn" for manager in managers):
        return "yarn"
    if any(manager == "npm" for manager in managers):
        return "npm"
    if any(path.endswith("pnpm-lock.yaml") for path in repo_context.lockfiles):
        return "pnpm"
    if any(path.endswith("yarn.lock") for path in repo_context.lockfiles):
        return "yarn"
    if any(path.endswith(("package-lock.json", "npm-shrinkwrap.json")) for path in repo_context.lockfiles):
        return "npm"
    return None


def preferred_workflow_path(repo_context: Optional[RepoContext]) -> Optional[str]:
    if repo_context is None:
        return None
    for candidate in repo_context.candidate_files:
        if candidate.path.startswith(".github/workflows/"):
            return candidate.path
    if repo_context.workflow_files:
        return repo_context.workflow_files[0]
    return None


def primary_python_manifest(repo_context: Optional[RepoContext]) -> Optional[str]:
    if repo_context is None:
        return None
    preferred = ("pyproject.toml", "requirements.txt", "Pipfile", "setup.py", "setup.cfg")
    manifest_names = {Path(path).name: path for path in repo_context.manifests}
    for name in preferred:
        if name in manifest_names:
            return manifest_names[name]
    return None


def _scan_repo_files(root: Path) -> tuple[List[str], Dict[str, int | bool]]:
    repo_files: List[str] = []
    truncated = False

    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        for filename in sorted(filenames):
            full_path = Path(current_root, filename)
            try:
                rel_path = full_path.relative_to(root).as_posix()
            except ValueError:
                continue
            repo_files.append(rel_path)
            if len(repo_files) >= MAX_SCANNED_FILES:
                truncated = True
                break
        if truncated:
            break

    return repo_files, {"scanned_files": len(repo_files), "scan_truncated": truncated}


def _extract_package_json_details(
    root: Path,
    manifests: Sequence[str],
) -> tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    package_scripts: Dict[str, Dict[str, str]] = {}
    package_managers: Dict[str, str] = {}

    for manifest in manifests:
        if Path(manifest).name != "package.json":
            continue
        text = _read_text_file(root / manifest)
        if text is None:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue

        scripts = payload.get("scripts")
        if isinstance(scripts, dict):
            package_scripts[manifest] = {
                str(name): str(command)
                for name, command in scripts.items()
                if isinstance(name, str) and isinstance(command, str)
            }

        manager = _package_manager_from_package_json(payload)
        if manager:
            package_managers[manifest] = manager

    return package_scripts, package_managers


def _package_manager_from_package_json(payload: dict) -> Optional[str]:
    package_manager = payload.get("packageManager")
    if isinstance(package_manager, str):
        if package_manager.startswith("pnpm@"):
            return "pnpm"
        if package_manager.startswith("yarn@"):
            return "yarn"
        if package_manager.startswith("npm@"):
            return "npm"

    if payload.get("pnpm"):
        return "pnpm"
    return None


def _extract_tool_versions(
    root: Path,
    workflow_files: Sequence[str],
    manifests: Sequence[str],
    package_managers: Dict[str, str],
) -> Dict[str, List[str]]:
    tool_versions: Dict[str, List[str]] = defaultdict(list)

    for workflow in workflow_files:
        text = _read_text_file(root / workflow)
        if text is None:
            continue
        for tool, pattern in _SETUP_TOOL_VERSION_PATTERNS.items():
            for match in pattern.findall(text):
                value = match.strip()
                if value:
                    tool_versions[tool].append(f"{value} ({workflow})")

    for manifest in manifests:
        if Path(manifest).name == "pyproject.toml":
            text = _read_text_file(root / manifest)
            if text is None:
                continue
            try:
                payload = tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                continue
            requires_python = payload.get("project", {}).get("requires-python")
            if isinstance(requires_python, str):
                tool_versions["python"].append(f"{requires_python} ({manifest})")

        if Path(manifest).name == "package.json":
            text = _read_text_file(root / manifest)
            if text is None:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            node_version = payload.get("engines", {}).get("node")
            if isinstance(node_version, str):
                tool_versions["node"].append(f"{node_version} ({manifest})")

    for manifest, manager in package_managers.items():
        tool_versions["package_manager"].append(f"{manager} ({manifest})")

    return {tool: _dedupe_preserve_order(values) for tool, values in tool_versions.items()}


def _extract_candidate_files(raw_log_text: str, repo_files_set: set[str]) -> List[RepoCandidateFile]:
    found: Dict[str, RepoCandidateFile] = {}

    def add(path: Optional[str], reason: str, line_hint: Optional[int] = None) -> None:
        if not path:
            return
        existing = found.get(path)
        if existing is None:
            found[path] = RepoCandidateFile(path=path, reason=reason, line_hint=line_hint)
            return
        reason_parts = _dedupe_preserve_order([existing.reason, reason])
        found[path] = RepoCandidateFile(
            path=path,
            reason="; ".join(reason_parts),
            line_hint=existing.line_hint or line_hint,
        )

    for match in _PY_TRACEBACK_RE.finditer(raw_log_text):
        resolved = _resolve_logged_path(match.group("path"), repo_files_set)
        add(resolved, "python traceback location", line_hint=int(match.group("line")))

    source_files: List[str] = []
    for match in _LINE_COL_RE.finditer(raw_log_text):
        resolved = _resolve_logged_path(match.group("path"), repo_files_set)
        if not resolved:
            continue
        source_files.append(resolved)
        add(resolved, "error location from log", line_hint=int(match.group("line")))

    for match in _GENERIC_PATH_RE.finditer(raw_log_text):
        resolved = _resolve_logged_path(match.group("path"), repo_files_set)
        if resolved:
            source_files.append(resolved)
            add(resolved, "path referenced in log")

    for match in _IMPORT_FROM_SOURCE_RE.finditer(raw_log_text):
        source = _resolve_logged_path(match.group("source"), repo_files_set)
        if source:
            source_files.append(source)
            add(source, "import error source file")
        resolved_import = _resolve_import_path(match.group("import"), source, repo_files_set)
        add(resolved_import, f"resolved import path {match.group('import')!r}")

    for match in _TS_IMPORT_ERROR_RE.finditer(raw_log_text):
        source = _resolve_logged_path(match.group("source"), repo_files_set)
        if source:
            source_files.append(source)
            add(source, "TypeScript import error source", line_hint=int(match.group("line")))
        resolved_import = _resolve_import_path(match.group("import"), source, repo_files_set)
        add(resolved_import, f"resolved import path {match.group('import')!r}")

    for source in list(_dedupe_preserve_order(source_files))[:10]:
        for import_match in re.finditer(r"['\"](\.{1,2}/[^'\"]+|[A-Za-z0-9_./-]+/[A-Za-z0-9_./-]+)['\"]", raw_log_text):
            resolved_import = _resolve_import_path(import_match.group(1), source, repo_files_set)
            add(resolved_import, f"possible import path {import_match.group(1)!r} near {source}")

    return sorted(found.values(), key=lambda item: item.path)[:12]


def _resolve_logged_path(raw_path: str, repo_files_set: set[str]) -> Optional[str]:
    cleaned = raw_path.strip().replace("\\", "/")
    if not cleaned or cleaned.startswith(("http://", "https://")):
        return None

    posix_path = PurePosixPath(cleaned).as_posix()
    if posix_path in repo_files_set:
        return posix_path
    if posix_path.startswith("./") and posix_path[2:] in repo_files_set:
        return posix_path[2:]
    if posix_path.startswith("/") and posix_path[1:] in repo_files_set:
        return posix_path[1:]
    return None


def _resolve_import_path(import_path: str, source_path: Optional[str], repo_files_set: set[str]) -> Optional[str]:
    cleaned = import_path.strip().replace("\\", "/")
    if not cleaned or cleaned.startswith(("@", "#")):
        return None

    candidates: List[str] = []
    if source_path and cleaned.startswith((".", "..")):
        base_dir = PurePosixPath(source_path).parent
        candidates.extend(_expand_import_candidates((base_dir / cleaned).as_posix()))
    elif "/" in cleaned:
        candidates.extend(_expand_import_candidates(cleaned))

    for candidate in candidates:
        normalized = PurePosixPath(candidate).as_posix()
        if normalized in repo_files_set:
            return normalized
    return None


def _expand_import_candidates(path_without_suffix: str) -> Iterable[str]:
    if PurePosixPath(path_without_suffix).suffix:
        return [path_without_suffix]

    out = [path_without_suffix]
    for suffix in RESOLVABLE_IMPORT_SUFFIXES:
        out.append(f"{path_without_suffix}{suffix}")
        out.append(f"{path_without_suffix}/index{suffix}")
    return out


def _build_tree_sample(
    repo_files: Sequence[str],
    manifests: Sequence[str],
    lockfiles: Sequence[str],
    workflow_files: Sequence[str],
    candidate_files: Sequence[RepoCandidateFile],
    max_entries: int = 18,
) -> List[str]:
    top_level = sorted(
        {
            f"{entry.split('/', 1)[0]}/" if "/" in entry else entry
            for entry in repo_files[:200]
        }
    )
    prioritized = top_level + list(manifests) + list(lockfiles) + list(workflow_files) + [
        candidate.path for candidate in candidate_files
    ]
    return _dedupe_preserve_order(prioritized)[:max_entries]


def _select_snippets(
    *,
    root: Path,
    report: RCAReport,
    candidate_files: Sequence[RepoCandidateFile],
    manifests: Sequence[str],
    lockfiles: Sequence[str],
    workflow_files: Sequence[str],
    max_snippets: int = 5,
) -> List[RepoSnippet]:
    wanted: List[tuple[str, str, Optional[int]]] = []
    wanted.extend((candidate.path, candidate.reason, candidate.line_hint) for candidate in candidate_files)

    if report.failure_class == "workflow_configuration_error":
        wanted.extend((path, "workflow definition", None) for path in workflow_files)
    elif report.failure_class == "environment_dependency_failure":
        wanted.extend((path, "dependency manifest", None) for path in manifests)
        wanted.extend((path, "dependency lockfile", None) for path in lockfiles)
        wanted.extend((path, "workflow install context", None) for path in workflow_files)
    elif report.failure_class == "build_failure":
        wanted.extend((path, "build manifest", None) for path in manifests)
        wanted.extend((path, "workflow build context", None) for path in workflow_files)
    else:
        wanted.extend((path, "repo manifest", None) for path in manifests)
        wanted.extend((path, "workflow file", None) for path in workflow_files)

    snippets: List[RepoSnippet] = []
    seen: set[str] = set()
    for path, reason, line_hint in wanted:
        if path in seen:
            continue
        text = _read_snippet(root / path, line_hint=line_hint)
        if text is None:
            continue
        snippets.append(RepoSnippet(path=path, reason=reason, content=text))
        seen.add(path)
        if len(snippets) >= max_snippets:
            break

    return snippets


def _read_snippet(path: Path, line_hint: Optional[int]) -> Optional[str]:
    text = _read_text_file(path)
    if text is None:
        return None

    lines = text.splitlines()
    if not lines:
        return ""

    if line_hint is not None and line_hint > 0:
        start = max(1, line_hint - 5)
        end = min(len(lines), line_hint + 8)
        selected = lines[start - 1:end]
        numbered = [f"{idx}: {value}" for idx, value in enumerate(selected, start=start)]
    else:
        selected = lines[:MAX_SNIPPET_LINES]
        numbered = [f"{idx}: {value}" for idx, value in enumerate(selected, start=1)]

    rendered = "\n".join(numbered)
    if len(lines) > len(selected):
        rendered += "\n..."
    return rendered


def _read_text_file(path: Path) -> Optional[str]:
    if path.suffix and path.suffix not in TEXT_SNIPPET_SUFFIXES and path.name not in {
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "Pipfile",
        "Gemfile",
        "yarn.lock",
    }:
        return None
    try:
        raw = path.read_bytes()[:MAX_SNIPPET_BYTES]
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
