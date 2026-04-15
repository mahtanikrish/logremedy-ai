from gha_remediator import prompts
from gha_remediator.pipeline import GHARemediator
from gha_remediator.rag import KnowledgeBase
from gha_remediator.remediation.llm_planner import plan_with_llm
from gha_remediator.remediation.templates import choose_template, render_plan
from gha_remediator.repo_context import build_repo_context
from gha_remediator.types import (
    LogBlock,
    LogLine,
    RCAReport,
    RepoCandidateFile,
    RepoContext,
)


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_report(failure_class: str, lines: list[str]) -> RCAReport:
    log_lines = [LogLine(idx, text) for idx, text in enumerate(lines, start=1)]
    return RCAReport(
        failure_class=failure_class,
        key_lines=log_lines,
        blocks=[LogBlock(start=1, end=len(log_lines), lines=log_lines)],
        root_causes=["Build import failed."],
        metadata={},
    )


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
                "      - uses: actions/setup-node@v4",
                "        with:",
                "          node-version: 20",
                "      - uses: actions/setup-python@v5",
                "        with:",
                '          python-version: "3.12"',
                "      - run: npm ci",
                "      - run: npm run build",
            ]
        ),
    )
    _write(
        tmp_path / "pyproject.toml",
        "\n".join(
            [
                "[project]",
                'name = "sample-app"',
                'requires-python = ">=3.11"',
            ]
        ),
    )
    _write(
        tmp_path / "frontend" / "package.json",
        "\n".join(
            [
                "{",
                '  "name": "frontend",',
                '  "packageManager": "npm@10.8.1",',
                '  "engines": { "node": ">=20" },',
                '  "scripts": {',
                '    "build": "vite build",',
                '    "test": "vitest run"',
                "  }",
                "}",
            ]
        ),
    )
    _write(tmp_path / "frontend" / "package-lock.json", '{ "name": "frontend" }')
    _write(
        tmp_path / "frontend" / "src" / "index.ts",
        "\n".join(
            [
                "import { helper } from './utils/helper';",
                "",
                "export function run() {",
                "  return helper();",
                "}",
            ]
        ),
    )
    _write(
        tmp_path / "frontend" / "src" / "utils" / "helper.ts",
        "\n".join(
            [
                "export function helper() {",
                "  return 'ok';",
                "}",
            ]
        ),
    )


def test_build_repo_context_extracts_repo_summary_and_candidates(tmp_path):
    _seed_repo(tmp_path)
    raw_log = "\n".join(
        [
            "build failed",
            "frontend/src/index.ts(4,1): error TS2307: Cannot find module './utils/helper' or its corresponding type declarations.",
            "    at Object.<anonymous> (frontend/src/index.ts:4:1)",
        ]
    )
    report = _make_report("build_failure", [raw_log])

    repo_context = build_repo_context(str(tmp_path), raw_log, report)

    assert "pyproject.toml" in repo_context.manifests
    assert "frontend/package.json" in repo_context.manifests
    assert "frontend/package-lock.json" in repo_context.lockfiles
    assert ".github/workflows/ci.yml" in repo_context.workflow_files
    assert repo_context.package_scripts["frontend/package.json"]["build"] == "vite build"
    assert repo_context.package_managers["frontend/package.json"] == "npm"
    assert any(value.startswith("20") for value in repo_context.tool_versions["node"])
    assert any(value.startswith(">=3.11") for value in repo_context.tool_versions["python"])
    assert {candidate.path for candidate in repo_context.candidate_files} >= {
        "frontend/src/index.ts",
        "frontend/src/utils/helper.ts",
    }
    assert {snippet.path for snippet in repo_context.snippets} >= {
        "frontend/src/index.ts",
        "frontend/package.json",
        ".github/workflows/ci.yml",
    }


def test_build_repo_context_preserves_missing_repo_relative_targets(tmp_path):
    _write(
        tmp_path / "docs" / "package.json",
        "\n".join(
            [
                "{",
                '  "name": "docs",',
                '  "scripts": {',
                '    "build": "vitepress build"',
                "  }",
                "}",
            ]
        ),
    )
    _write(tmp_path / "docs" / "package-lock.json", '{ "name": "docs" }')
    _write(
        tmp_path / "docs" / "ar-SA" / "presets" / "catppuccin-powerline.md",
        "# Preset\n\n```toml\n@include public/presets/toml/catppuccin-powerline.toml\n```\n",
    )
    (tmp_path / "docs" / "public" / "presets" / "toml").mkdir(parents=True, exist_ok=True)

    raw_log = "\n".join(
        [
            "build error:",
            "[vitepress] ENOENT: no such file or directory, stat '/home/runner/work/starship/starship/docs/public/presets/toml/catppuccin-powerline.toml'",
            "file: /home/runner/work/starship/starship/docs/ar-SA/presets/catppuccin-powerline.md",
        ]
    )
    report = _make_report("build_failure", raw_log.splitlines())

    repo_context = build_repo_context(str(tmp_path), raw_log, report)

    candidate_paths = {candidate.path for candidate in repo_context.candidate_files}
    assert "docs/public/presets/toml/catppuccin-powerline.toml" in candidate_paths
    assert "docs/ar-SA/presets/catppuccin-powerline.md" in candidate_paths
    assert "docs/public/presets/toml/catppuccin-powerline.toml" in repo_context.tree_entries


class _CapturePlannerLLM:
    def __init__(self):
        self.calls = []

    def generate_json(self, *, system, user, schema_hint, cfg):
        self.calls.append({"system": system, "user": user, "schema_hint": schema_hint})
        return {
            "fix_type": "llm_plan",
            "risk_level": "low",
            "patches": [],
            "commands": [],
            "assumptions": ["Use the existing build path."],
            "rollback": [],
        }


def test_plan_with_llm_includes_repo_context_in_prompt(tmp_path):
    _seed_repo(tmp_path)
    raw_log = "build failed\nfrontend/src/index.ts(4,1): error TS2307: Cannot find module './utils/helper'"
    report = _make_report("build_failure", raw_log.splitlines())
    repo_context = build_repo_context(str(tmp_path), raw_log, report)
    llm = _CapturePlannerLLM()

    plan = plan_with_llm(report, docs=[], repo_context=repo_context, llm=llm)

    assert plan.evidence["repo_context_used"] is True
    prompt = llm.calls[0]["user"]
    assert "Repository context:" in prompt
    assert "frontend/package.json" in prompt
    assert "frontend/src/index.ts" in prompt
    assert "Relevant repo snippets:" in prompt


def test_render_plan_uses_repo_context_for_package_manager():
    report = _make_report("build_failure", ["build step failed"])
    repo_context = RepoContext(
        repo_root="/tmp/repo",
        tree_entries=["frontend/", "frontend/package.json", "frontend/pnpm-lock.yaml"],
        manifests=["frontend/package.json"],
        lockfiles=["frontend/pnpm-lock.yaml"],
        workflow_files=[],
        package_scripts={"frontend/package.json": {"build": "vite build"}},
        package_managers={"frontend/package.json": "pnpm"},
        tool_versions={},
        candidate_files=[],
        snippets=[],
        metadata={},
    )

    template = choose_template(report, repo_context=repo_context)
    plan = render_plan(report, template, repo_context=repo_context)

    assert template.fix_type == "node_typescript_build_fix"
    assert plan.commands == ["pnpm install --frozen-lockfile", "pnpm run build"]
    assert any("frontend/package.json" in item for item in plan.assumptions)
    assert plan.evidence["repo_context_used"] is True


def test_render_plan_uses_detected_workflow_path():
    report = _make_report("workflow_configuration_error", ["workflow invalid yaml syntax error"])
    repo_context = RepoContext(
        repo_root="/tmp/repo",
        tree_entries=[".github/", ".github/workflows/", ".github/workflows/ci.yml"],
        manifests=[],
        lockfiles=[],
        workflow_files=[".github/workflows/ci.yml"],
        package_scripts={},
        package_managers={},
        tool_versions={},
        candidate_files=[RepoCandidateFile(path=".github/workflows/ci.yml", reason="workflow parse failure")],
        snippets=[],
        metadata={},
    )

    template = choose_template(report, repo_context=repo_context)
    plan = render_plan(report, template, repo_context=repo_context)

    assert plan.rollback == ["git checkout -- .github/workflows/ci.yml"]
    assert plan.assumptions == ["Workflow issue is likely in .github/workflows/ci.yml."]


class _PipelineLLM:
    def __init__(self):
        self.calls = []

    def generate_json(self, *, system, user, schema_hint, cfg):
        self.calls.append({"system": system, "user": user})
        if system == prompts.RCA_SYSTEM:
            return {
                "root_causes": ["Missing import path in the frontend build."],
                "confidence": 0.92,
                "evidence_line_numbers": [2],
                "notes": ["The source file imports a path that resolves inside src/utils."],
            }
        return {
            "fix_type": "llm_plan",
            "risk_level": "low",
            "patches": [],
            "commands": [],
            "assumptions": ["Focus on the candidate source file."],
            "rollback": [],
        }


def test_pipeline_run_builds_repo_context_before_planning(tmp_path):
    _seed_repo(tmp_path)
    raw_log = "\n".join(
        [
            "build failed",
            "frontend/src/index.ts(4,1): error TS2307: Cannot find module './utils/helper' or its corresponding type declarations.",
        ]
    )
    llm = _PipelineLLM()
    remediator = GHARemediator(kb=KnowledgeBase([]), llm=llm)

    result = remediator.run(raw_log_text=raw_log, repo=str(tmp_path), replay=False, job=None)

    assert result["verification"]["status"] == "accepted"
    assert result["rca"]["confidence"] == 0.92
    assert result["rca"]["evidence_line_numbers"] == [2]
    assert result["rca"]["notes"] == ["The source file imports a path that resolves inside src/utils."]
    repo_context = result["remediation"]["evidence"]["repo_context"]
    assert any(item["path"] == "frontend/src/index.ts" for item in repo_context["candidate_files"])
    assert any(item["path"] == "frontend/src/utils/helper.ts" for item in repo_context["candidate_files"])
    assert llm.calls[1]["system"] == prompts.PLAN_SYSTEM
    assert "Repository context:" in llm.calls[1]["user"]


def test_pipeline_run_without_repo_skips_verification_and_preserves_planning():
    raw_log = "\n".join(
        [
            "Step: Run application",
            "Traceback (most recent call last):",
            '  File "app.py", line 1, in <module>',
            "    import requests",
            "ModuleNotFoundError: No module named 'requests'",
            "Error: Process completed with exit code 1.",
        ]
    )
    remediator = GHARemediator(kb=KnowledgeBase([]), llm=None)

    result = remediator.run(raw_log_text=raw_log, repo=None, replay=False, job=None)

    assert result["remediation"]["fix_type"] == "python_add_dependency"
    assert result["remediation"]["evidence"]["repo_context"]["metadata"]["scan_error"] == "repo not provided"
    assert result["verification"]["status"] == "inconclusive"
    assert result["verification"]["reason"] == "verification skipped: repo not provided"
    assert result["verification"]["evidence"]["capability"]["selected_validator"] == "none"
