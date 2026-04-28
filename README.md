# AI-Powered GitHub Actions Log Analysis and Remediation System

> Final Year Project — UCL Computer Science x Microsoft

A production-ready pipeline for analysing GitHub Actions failure logs, performing root-cause analysis (RCA), and proposing remediations. All generated fixes are treated as hypotheses and passed through deterministic verification gates before they are surfaced to the user.

---

## The Problem

LLM-generated CI fixes are not trustworthy by default: a model can confidently suggest a patch that targets the wrong file, runs an unsafe command, or recommends a package that does not exist. This system treats model output as a candidate remediation and validates it before accepting it.

---

## Pipeline Overview

```text
Raw CI log
    |
    v
1. Log Preprocessing      - ANSI strip, keyword filter, asymmetric context expansion,
                            token-budget pruning
    |
    v
2. Failure Classification - Rule-based: dependency / test / build / workflow / infra
    |
    v
3. Root-Cause Analysis    - LLM with curated evidence blocks
    |
    v
4. BM25 Retrieval         - Lexical retrieval from a local knowledge base
    |
    v
5. Repo Context           - Scan repo tree, manifests, lockfiles, workflows,
                            scripts, candidate files, and snippets
    |
    v
6. Remediation Planning   - Template-based by default, with LLM planning support
    |
    v
7. Verification Gates     - See below
    |
    v
Structured JSON output    - rca / remediation / verification
```

---

## Verification Gates

Gates run sequentially and stop on the first hard failure.

| Gate | Name | What it checks |
|------|------|----------------|
| A | Preconditions | Repo exists and a verification workspace can be prepared |
| B | Policy | Patch size, target paths, and commands satisfy the safety policy |
| C | Grounding | Proposed patches and commands are grounded in repo context and failure evidence |
| D | Patch apply | Patches apply cleanly in the workspace copy |
| E | Static validation | Touched files pass basic parse and syntax checks |
| F | Adapter check | A deterministic validator passes for the selected remediation type |
| G | Sandbox | Commands run locally, or Python dependency fixes verify in an isolated venv |
| H | Replay (optional) | Workflow replay via `act` when configured |

Verification statuses produced by the runtime include:

- `verified`
- `accepted`
- `rejected_precondition`
- `rejected_policy`
- `rejected_grounding`
- `rejected_unappliable`
- `rejected_static`
- `rejected_adapter_check`
- `rejected_execution`
- `failed_replay`
- `inconclusive`

---

## Runtime Entrypoints

- `gha-remediator`
- `gha-remediator-web`
- `python -m gha_remediator`
- `python -m gha_remediator.web_app`

---

## Prerequisites

- Python 3.10+
- Node.js 18+ for frontend development
- `GITHUB_TOKEN` for LLM-backed runtime flows and GitHub Actions log ingestion
- [`act`](https://github.com/nektos/act) if you want replay verification

---

## Install

Core runtime:

```bash
pip install -e .
```

Web app:

```bash
pip install -e ".[web]"
cd frontend
npm install
```

Testing:

```bash
pip install -e ".[dev,web]"
cd frontend
npm install
```

---

## Quick Start

### Run the CLI on a local log

```bash
export GITHUB_TOKEN=<your-token>
python -m gha_remediator run \
  --log /path/to/failure.log \
  --repo /path/to/repository \
  --model gpt-4o-mini
```

### Save output to file

```bash
python -m gha_remediator run \
  --log /path/to/failure.log \
  --repo /path/to/repository \
  --out result.json
```

### Run with replay

```bash
python -m gha_remediator run \
  --log /path/to/failure.log \
  --repo /path/to/repository \
  --replay
```

### Inspect extracted repo context

This command does not call the LLM.

```bash
python -m gha_remediator inspect-context \
  --log /path/to/failure.log \
  --repo /path/to/repository
```

### Inspect the exact planner input

This command also avoids the LLM call and prints the planner inputs.

```bash
python -m gha_remediator debug-plan-input \
  --log /path/to/failure.log \
  --repo /path/to/repository
```

### Run without a repo

If `--repo` is omitted, the system still performs RCA and remediation planning, but verification is reported as inconclusive because repo-aware validation cannot run.

```bash
python -m gha_remediator run \
  --log /path/to/failure.log \
  --model gpt-4o-mini
```

---

## Web App

### Development mode

Run the Flask backend:

```bash
python -m gha_remediator.web_app
```

Run the frontend:

```bash
cd frontend
npm run dev
```

Then open [http://127.0.0.1:5173](http://127.0.0.1:5173).

### Built mode

```bash
cd frontend
npm run build
cd ..
python -m gha_remediator.web_app
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Web app analysis modes

- Upload or paste a local CI log and optionally provide a local repo path for verification
- Fetch the latest failed GitHub Actions run, or a specific run ID, for `owner/name`

---

## Configuration

Runtime settings are stored in:

- `~/.gha-remediator/web-settings.json`
- or the path set by `GHA_REMEDIATOR_SETTINGS_PATH`

The web app settings support:

- `knowledge_base_path` for a custom local knowledge base
- `env_file_path` for loading `GITHUB_TOKEN` from an env file

If no knowledge base path is configured, the runtime falls back to a small built-in knowledge base.

---

## Environment Variables

| Variable | Required for |
|----------|-------------|
| `GITHUB_TOKEN` | LLM-backed analysis and GitHub Actions log ingestion |
| `GHA_REMEDIATOR_SETTINGS_PATH` | Override the default settings file location |
| `PORT` | Override the default Flask port in web mode |

---

## Output Format

The system returns structured JSON with three top-level sections:

```json
{
  "rca": {
    "failure_class": "environment_dependency_failure",
    "root_cause_label": "missing_python_dependency",
    "root_cause_text": "Missing Python dependency (module import failed).",
    "root_causes": ["Missing Python dependency (module import failed)."]
  },
  "remediation": {
    "fix_type": "python_add_dependency",
    "risk_level": "low",
    "commands": ["python -m pip install requests"],
    "guidance": ["Add the dependency to the project manifest used in CI."],
    "patches": []
  },
  "verification": {
    "status": "accepted",
    "reason": "accepted under supported validator python_dependency_manifest"
  }
}
```

---

## Project Structure

```text
gha_remediator/
├── cli.py
├── __main__.py
├── runtime_factory.py
├── pipeline.py
├── web_app.py
├── app_settings.py
├── types.py
├── logs.py
├── preprocess.py
├── classifier.py
├── rca.py
├── rag.py
├── repo_context.py
├── prompts.py
├── cli_support/
│   ├── dispatch.py
│   ├── payloads.py
│   ├── runtime_commands.py
│   ├── shared.py
│   └── __init__.py
├── ingestion/
│   ├── github_actions.py
│   └── synthetic_loader.py
├── llm/
│   ├── base.py
│   ├── github_models_client.py
│   └── __init__.py
├── remediation/
│   ├── guidance.py
│   ├── llm_planner.py
│   └── templates.py
├── services/
│   └── analysis_runtime.py
├── verification/
│   ├── adapters.py
│   ├── capability.py
│   ├── grounding.py
│   ├── policy.py
│   ├── replay.py
│   ├── sandbox.py
│   ├── static_checks.py
│   ├── venv_verifier.py
│   ├── verify.py
│   └── workspace.py
└── tests/
    ├── test_analysis_runtime.py
    ├── test_classify.py
    ├── test_github_actions_ingestion.py
    ├── test_policy.py
    ├── test_preprocess.py
    └── ...

frontend/
├── src/
│   ├── components/
│   ├── resultFormatting/
│   ├── api.js
│   ├── App.jsx
│   ├── appConfig.js
│   ├── main.jsx
│   ├── resultFormatting.js
│   ├── styles.css
│   └── viewModel.js
├── index.html
├── package.json
├── package-lock.json
└── vite.config.js
```

---

## Running Tests

Python:

```bash
pytest -q
```

Frontend:

```bash
cd frontend
npm test -- --test-reporter=spec
```
