export default function SettingsForm({
  knowledgeBasePath,
  envFilePath,
  isRunning,
  onKnowledgeBasePathChange,
  onEnvFilePathChange,
  onReload,
  onSave,
}) {
  return (
    <div className="form-card">
      <label className="field">
        <span>Knowledge base path</span>
        <input
          value={knowledgeBasePath}
          onChange={(event) => onKnowledgeBasePathChange(event.target.value)}
          placeholder="Optional file or directory path"
        />
        <small>Leave blank to use the built-in default knowledge base.</small>
      </label>

      <label className="field">
        <span>Env file path</span>
        <input
          value={envFilePath}
          onChange={(event) => onEnvFilePathChange(event.target.value)}
          placeholder="Optional .env file path"
        />
        <small>When set, the app will look for <code>GITHUB_TOKEN</code> in this file if it is not already in the environment.</small>
      </label>

      <div className="actions">
        <button className="secondary-action" onClick={onReload} disabled={isRunning} type="button">
          Reload Settings
        </button>
        <button className="primary-action" onClick={onSave} disabled={isRunning} type="button">
          {isRunning ? "Saving..." : "Save Settings"}
        </button>
      </div>
    </div>
  );
}
