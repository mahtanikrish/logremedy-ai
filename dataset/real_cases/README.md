# Real GitHub Actions Evaluation Cases

This directory is for manually curated real-world evaluation cases used in the dissertation.

Each case should be stored as one JSON file under `dataset/real_cases/cases/`.

Recommended workflow:

1. Choose a failed public GitHub Actions run.
2. Record the repository, run ID, workflow file, and a short annotation of the failure.
3. Save the raw combined log separately if needed, or store a reference to where it was collected from.
4. Keep the annotation small and consistent across cases.

You can generate a starting stub automatically:

```bash
python -m gha_remediator export-real-case \
  --github-repo owner/repository \
  --run-id 123456789
```

This writes:

- a combined raw log file under `dataset/real_cases/cases/`
- a matching JSON annotation stub you can edit manually

Suggested fields:

- `case_id`: stable identifier for the case
- `repo`: GitHub repository in `owner/name` form
- `run_id`: GitHub Actions run ID
- `workflow_name`: workflow display name if known
- `workflow_path`: workflow YAML path if known
- `failure_class`: one of the system failure classes
- `root_cause`: short human-written RCA
- `evidence_lines`: key lines supporting the root cause
- `notes`: optional annotation notes

Use `dataset/real_cases/case_schema.example.json` as the template.
