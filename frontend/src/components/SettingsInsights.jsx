function BulletPanel({ children }) {
  return <div className="bullet-panel">{children}</div>;
}

function BulletLine({ children }) {
  return (
    <div className="bullet-line">
      <span className="bullet-mark">-</span>
      <span>{children}</span>
    </div>
  );
}

export default function SettingsInsights({ settingsInfo, form }) {
  return (
    <div className="result-surface">
      <div className="report-view">
        <article className="report-card">
          <h4>Knowledge Base</h4>
          <p>Current retrieval source used by the backend.</p>
          <BulletPanel>
            <BulletLine>
              {settingsInfo?.knowledgeBase?.configured
                ? settingsInfo?.knowledgeBase?.error
                  ? settingsInfo.knowledgeBase.error
                  : `Configured path: ${settingsInfo.knowledgeBase.path || form.settings.knowledgeBasePath}`
                : "Using the built-in default knowledge base."}
            </BulletLine>
            <BulletLine>
              {settingsInfo?.knowledgeBase?.docCount
                ? `${settingsInfo.knowledgeBase.docCount} document(s) available for retrieval.`
                : "No external knowledge base documents loaded."}
            </BulletLine>
          </BulletPanel>
        </article>

        <article className="report-card">
          <h4>GitHub Token</h4>
          <p>How the app will resolve authentication for GitHub log fetches and model calls.</p>
          <BulletPanel>
            <BulletLine>
              {settingsInfo?.githubToken?.present
                ? settingsInfo.githubToken.source === "env_file"
                  ? `Token will be read from ${settingsInfo.githubToken.envFilePath}.`
                  : "Token is already available in the process environment."
                : "No GitHub token is currently available."}
            </BulletLine>
            <BulletLine>Settings file: {settingsInfo?.settingsFilePath || "Not saved yet"}.</BulletLine>
          </BulletPanel>
        </article>
      </div>
    </div>
  );
}
