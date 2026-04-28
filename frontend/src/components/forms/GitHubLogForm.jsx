export default function GitHubLogForm({
  repoName,
  runId,
  verifyRepo,
  isRunning,
  onRepoNameChange,
  onRunIdChange,
  onVerifyRepoChange,
  onSubmit,
}) {
  return (
    <div className="form-card">
      <label className="field">
        <span>GitHub repo (owner/name)</span>
        <input
          value={repoName}
          onChange={(event) => onRepoNameChange(event.target.value)}
          placeholder="owner/name"
        />
        <small>Example: mahtanikrish/actions-log-generator</small>
      </label>

      <label className="field">
        <span>Run ID</span>
        <input
          value={runId}
          onChange={(event) => onRunIdChange(event.target.value)}
          placeholder="Optional"
        />
        <small>Leave blank to use the latest failed run with downloadable logs.</small>
      </label>

      <label className="field">
        <span>Verification repo</span>
        <input
          value={verifyRepo}
          onChange={(event) => onVerifyRepoChange(event.target.value)}
          placeholder="Optional local repo path"
        />
        <small>Leave blank to skip verification, or use a local clone of the same repo for verification.</small>
      </label>

      <div className="actions">
        <button className="primary-action" onClick={onSubmit} disabled={isRunning} type="button">
          {isRunning ? "Running..." : "Run GitHub Analysis"}
        </button>
      </div>
    </div>
  );
}
