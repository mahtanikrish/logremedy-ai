# LCA CI Builds Repair: How We Should Use It

This note is the working reference for integrating the `lca-ci-builds-repair` dataset into the remediation project.

## What We Verified Locally

Using the downloaded dataset at `/Users/krishmahtani/Desktop/UCL/lca-ci-builds-repair-dataset`:

- `default` contains `68` cases across `29` repos.
- `old` contains `144` cases across `53` repos.
- `default` is not additive; it is the smaller subset of `old`.

From the current audit outputs:

- all `144/144` old-split cases are usable for `context extraction` style evaluation.
- all `144/144` old-split cases are usable for `verification in principle` because they include repo ID, failing SHA, workflow text, changed files, and gold diff.
- `0/144` old-split cases are compatible with the **current** patch policy without verifier changes.
- old split breakdown: `87` source-only repairs
- old split breakdown: `54` code-touching multi-surface repairs
- old split breakdown: `3` config/docs-only repairs

Materialization spot-check:

- sampled cases: `122`, `130`, `173`, `64`
- `4/4` downloaded successfully at the exact failing SHA
- `4/4` had the workflow file present at `sha_fail`
- `4/4` had all gold changed files present
- `4/4` passed `git apply --check` for the gold diff

Replay spot-check:

- case `122` (`autogluon/autogluon`) was used for an `act` replay probe
- the workflow can be targeted, but replay from this Codex execution environment is still blocked by Docker socket access
- this means local replay is **not disproven**, but it is also **not yet validated** here

Viable verifier expansion spot-check:

- the remediation repo now supports `--verification-profile benchmark_supported_files`
- gold patches for starter cases `122`, `64`, and `36` now pass:
  - policy
  - patch application
  - Python static validation
- they currently stop at `replay not configured`, which is the expected terminal gate without replay

## What It Is Good For

- `context extraction` evaluation:
  each case includes the failing workflow text, failed-step logs, repo identifier, and failing commit SHA.
- `verification-aware` evaluation:
  each case also includes the gold fix diff and changed files, so we can check whether our gates would accept, reject, or fail to validate a known-good repair.
- `end-to-end` candidate selection:
  with a local repo checkout at `sha_fail`, we can test `log -> RCA -> fix -> verification` on a grounded real failure/fix pair.

## What It Is Not

- It is not a drop-in benchmark harness for our system.
- The upstream JetBrains benchmark runner is built around pushing changes to a benchmark org and observing remote GitHub Actions runs.
- That is useful for their paper, but it is not the cleanest evaluation loop for this project.

## What We Should Reuse

- Reuse the **dataset** itself.
- Reuse the **gold diff**, `changed_files`, `sha_fail`, `sha_success`, workflow text, and failing logs.
- Do **not** make the JetBrains runner our main evaluation harness.

## Key Constraint in Our Current System

Our verifier currently allows patches only for:

- `.github/workflows/*`
- `requirements.txt`
- `pyproject.toml`
- `package.json`
- `package-lock.json`
- `pnpm-lock.yaml`
- `tsconfig.json`

That means normal source-code fixes are rejected at the policy gate today.

In practice, this blocks the entire audited LCA pool right now, because none of the gold repairs stay inside the current allowlist.

We now also have a benchmark-oriented profile that broadens support to existing files in validated classes such as:

- `.py`
- `.json`
- `.toml`
- `.yaml` / `.yml`
- `.cfg` / `.ini`

This broader profile also applies small patch-budget limits.

## Practical Evaluation Plan

### 1. Context / RCA track

Use LCA cases to test:

- preprocessing
- failure localization
- repo/workflow context extraction
- RCA quality

This does not require the full gold diff to be policy-compatible.

### 2. Verification track

Use a manually triaged LCA subset to test:

- whether our policy gate is too narrow
- whether static checks fire when workflow files are touched
- whether replay is feasible locally once we move outside the current Docker-socket limitation

Best initial verification candidates from the audit:

- case `122` — `autogluon/autogluon` — `timeseries/setup.py`
- case `64` — `lightly-ai/lightly` — `docs/source/getting_started/benchmarks/imagenette_benchmark.py`
- case `36` — `skypilot-org/skypilot` — `docs/source/conf.py`

These are still blocked by current policy, but they are the least invasive starting points for a controlled verifier expansion.

This is the most important track for demonstrating the dissertation contribution.

### 3. End-to-end track

Only run a smaller LCA subset here:

- low-difficulty cases
- small diffs
- low replay friction
- repos we can materialize locally

## Current Recommendation

- Treat LCA as the main real-data source for verification-aware evaluation.
- Treat LogSage as the main evidence/RCA-style source.
- Do not claim LCA is fully usable for replay until we finish a replay audit from an environment with working Docker access.

## Files Produced By The Audit

- audit script:
  `/Users/krishmahtani/Desktop/gha_verifiable_remediation_llm/scripts/audit_lca_dataset.py`
- default split summary:
  `/Users/krishmahtani/Desktop/gha_verifiable_remediation_llm/results/lca_audit/default_summary.json`
- old split summary:
  `/Users/krishmahtani/Desktop/gha_verifiable_remediation_llm/results/lca_audit/old_summary.json`
- old split shortlists:
  `/Users/krishmahtani/Desktop/gha_verifiable_remediation_llm/results/lca_audit/old_shortlists.json`
- materialization spot-check:
  `/Users/krishmahtani/Desktop/gha_verifiable_remediation_llm/results/lca_audit/repo_materialization_sample.json`
- replay probe:
  `/Users/krishmahtani/Desktop/gha_verifiable_remediation_llm/results/lca_audit/replay_case122_summary.json`
- viable profile gold-patch probe:
  `/Users/krishmahtani/Desktop/gha_verifiable_remediation_llm/results/lca_audit/gold_probe_viable_profile.json`

## How To Rerun

```bash
python3 /Users/krishmahtani/Desktop/gha_verifiable_remediation_llm/scripts/audit_lca_dataset.py \
  --dataset-root /Users/krishmahtani/Desktop/UCL/lca-ci-builds-repair-dataset \
  --config both \
  --top-n 20
```

## Immediate Next Step

Run `scripts/audit_lca_dataset.py` first, then use its shortlist outputs to choose a small batch of repo-backed cases for deeper validation.
