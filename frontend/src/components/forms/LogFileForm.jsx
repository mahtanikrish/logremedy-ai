export default function LogFileForm({
  logName,
  repo,
  isRunning,
  onFileChange,
  onRepoChange,
  onSubmit,
}) {
  return (
    <div className="form-card">
      <label className="field">
        <span>Log file</span>
        <label className="upload-field" htmlFor="synthetic-log-file">
          <input
            id="synthetic-log-file"
            type="file"
            accept=".log,.txt,.json,.out,.text"
            onChange={onFileChange}
          />
          <span className="upload-button">Choose Log File</span>
          <span className="upload-name">{logName || "No file selected"}</span>
        </label>
        <small>Select a local `.log` file and the browser will upload its contents for analysis.</small>
      </label>

      <label className="field">
        <span>Verification repo</span>
        <input
          value={repo}
          onChange={(event) => onRepoChange(event.target.value)}
          placeholder="Optional local repo path"
        />
        <small>Leave blank to skip verification, or provide the matching local repo for repo-aware checks.</small>
      </label>

      <div className="actions">
        <button className="primary-action" onClick={onSubmit} disabled={isRunning} type="button">
          {isRunning ? "Running..." : "Run Log Analysis"}
        </button>
      </div>
    </div>
  );
}
