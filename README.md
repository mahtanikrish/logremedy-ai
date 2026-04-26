# AI-Powered GitHub Actions Log Analysis and Remediation System

> Final Year Project — UCL Computer Science x Microsoft

A multi agent system that analyses GitHub Actions failure logs, performs root-cause analysis (RCA) and proposes remediations — all gated behind a multi-stage verification pipeline to ensure fixes are safe and applicable before they are surfaced to the user.


---

## The Problem

LLM-generated fixes for CI failures are unverifiable by default: a model can confidently propose a patch that targets the wrong file, uses a banned command or installs a package that does not exist. This system treats LLM outputs as **hypotheses** and subjects them to deterministic verification gates before accepting them as valid remediations.

---

## Pipeline Overview

```
Raw CI log
    │
    ▼
1. Log Preprocessing      — ANSI strip, keyword filter, asymmetric context expansion,
                            token-budget pruning (LogSage-inspired)
    │
    ▼
2. Failure Classification — Rule-based: dependency / test / build / workflow / infra
    │
    ▼
3. Root-Cause Analysis    — LLM with curated evidence blocks
    │
    ▼
4. BM25 Retrieval         — Lexical retrieval from local knowledge base
    │
    ▼
5. Repo Context           — Scan repo tree, detect manifests / lockfiles / workflows,
                            extract scripts, tool versions, candidate files, snippets
    │
    ▼
6. Remediation Planning   — Template-based (default) or LLM planner with RAG + repo context
    │
    ▼
7. Verification Gates     — See below
    │
    ▼
Structured JSON output    — rca / remediation / verification
```

---

## Verification Gates

The core research contribution. Gates run sequentially; the first failure short-circuits the pipeline.

| Gate | Name | What it checks |
|------|------|----------------|
| A | Preconditions | All files referenced by patches exist in the repo |
| B | Safety policy | Patches only touch allowed paths; commands match an allowlist |
| C | Static validation | Workflow YAML files parse without syntax errors |
| C.5 | Sandbox | Python deps: `pip install` in an isolated venv; other commands: run locally |
| D | CI replay (optional) | Full workflow replay via `act` if installed |

**Verification outcomes:** `verified` · `rejected_precondition` · `rejected_policy` · `rejected_static` · `failed_replay` · `inconclusive`

---

## Prerequisites

- Python 3.10+
- `pip install -e .` to install the package in editable mode
- [`act`](https://github.com/nektos/act) — required for `--replay` (Gate D CI replay)

---

## Quick Start

### Run as a local web app
```bash
pip install -e ".[web]"
```

#### Development mode
```bash
python -m gha_remediator.web_app
```

```bash
cd frontend
npm install
npm run dev
```

Then open `http://127.0.0.1:5173`.

#### Single-process built mode
```bash
cd frontend
npm install
npm run build
cd ..
python -m gha_remediator.web_app
```

Then open `http://127.0.0.1:8000`.


### Run the pipeline
```bash
export GITHUB_TOKEN=<your-token>
python -m gha_remediator run \
  --log examples/failure_module_not_found.log \
  --repo . \
  --model gpt-4o-mini
```

### With CI replay (Gate D)
```bash
# Requires act: https://github.com/nektos/act
python -m gha_remediator run \
  --log examples/failure_module_not_found.log \
  --repo . --replay
```

### Save output to file
```bash
python -m gha_remediator run \
  --log examples/failure_module_not_found.log \
  --repo . \
  --out result.json
```

### Inspect extracted repo context
This command does not call the LLM. It is useful for checking exactly what was detected from the repo before planning.

```bash
python -m gha_remediator inspect-context \
  --log examples/failure_module_not_found.log \
  --repo .
```

It prints JSON including:
- `repo_context`
- `repo_context_summary`
- detected workflows, manifests, lockfiles, tool versions
- candidate target files and file snippets

### Inspect the exact planner input
This command also avoids the LLM call. It shows the prompts and structured inputs that would be sent into remediation planning.

```bash
python -m gha_remediator debug-plan-input \
  --log examples/failure_module_not_found.log \
  --repo .
```

It prints JSON including:
- `system_prompt`
- `schema_hint`
- `retrieved_docs`
- `repo_context`
- `user_prompt`

### Run without a repo
If `--repo` is omitted, the pipeline still performs RCA and remediation planning, but repo-aware extraction is replaced with a `repo not provided` marker and verification is skipped.

```bash
python -m gha_remediator run \
  --log examples/failure_module_not_found.log \
  --model gpt-4o-mini
```

Expected verification output in this mode:
- `status: inconclusive`
- `reason: verification skipped: repo not provided`

---

## Running the Synthetic Dataset

The `dataset/synthetic/` directory contains labelled failure logs with ground truth.

```bash
# Run on a synthetic log
python -m gha_remediator run \
  --log dataset/synthetic/dependency_errors/missing_module_01.log \
  --repo .
```

If you want plan-only synthetic evaluation without a checkout, `--repo` is optional for `run` and `eval-synthetic`. In that mode verification will be reported as skipped / inconclusive.

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest -v
```

---

## Environment Variables

| Variable | Required for |
|----------|-------------|
| `GITHUB_TOKEN` | `run`, `eval-synthetic`, `export-real-case`, and web app LLM execution |

`inspect-context` and `debug-plan-input` do not require `GITHUB_TOKEN` because they do not call the model.

---

## Project Structure

```
gha_remediator/
├── cli.py                  Entry point and argument parsing
├── pipeline.py             GHARemediator orchestrator
├── types.py                Core data structures (LogLine, RCAReport, RemediationPlan, ...)
├── logs.py                 Log parsing, ANSI stripping, success template extraction
├── preprocess.py           Evidence extraction: filter → expand → prune
├── classifier.py           Rule-based failure classification
├── rca.py                  Root-cause analysis
├── rag.py                  BM25 retrieval and KnowledgeBase
├── prompts.py              LLM system prompts and schema hints
├── llm/
│   ├── base.py             LLMClient protocol and LLMConfig
│   ├── github_models_client.py   GitHub Models API (Azure backend)
│   └── openai_client.py    OpenAI Responses API
├── remediation/
│   ├── templates.py        Template-based remediation planning
│   └── llm_planner.py      LLM-based remediation planning
├── verification/
│   ├── verify.py           Multi-gate verification orchestrator
│   ├── policy.py           Safety policy (allowlists for paths and commands)
│   ├── static_checks.py    YAML syntax validation, file existence checks
│   ├── venv_verifier.py    Isolated venv sandbox for Python dependency verification
│   ├── sandbox.py          Host-level sandbox for non-Python commands
│   └── replay.py           Optional CI replay via act
├── ingestion/
│   ├── synthetic_loader.py Load synthetic failure logs with ground truth
│   └── github_actions.py   Placeholder for future GitHub API integration
├── evaluation/
│   └── logger.py           Record verification results to JSON
└── tests/
    ├── test_classify.py    Failure classification tests
    ├── test_preprocess.py  Log preprocessing pipeline tests
    ├── test_policy.py      Safety policy (command + path) tests
    ├── test_static.py      Static validation tests
    └── test_venv_verifier.py  Venv sandbox verifier tests
```

---

## Output Format

The system outputs structured JSON covering all three pipeline stages:

```json
{
  "rca": {
    "failure_class": "environment_dependency_failure",
    "root_causes": ["Missing Python dependency (module import failed)."],
    "metadata": { "rca_mode": "heuristic", "num_lines": 12 }
  },
  "remediation": {
    "fix_type": "python_add_dependency",
    "risk_level": "low",
    "commands": ["python -m pip install requests"],
    "assumptions": ["Python package name is 'requests'"],
    "rollback": ["python -m pip uninstall -y requests"],
    "patches": []
  },
  "verification": {
    "status": "verified",
    "reason": "venv sandbox: pip install succeeded",
    "evidence": { "gate": "venv_sandbox", "package": "requests", "returncode": 0 }
  }
}
```
