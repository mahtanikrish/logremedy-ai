export default function WorkflowSidebar({ page, onSelectPage, pageCopy }) {
  return (
    <aside className="sidebar">
      <h2>Workflows</h2>

      <div className="workflow-switcher">
        <button
          className={page === "synthetic" ? "workflow-button active" : "workflow-button"}
          onClick={() => onSelectPage("synthetic")}
          type="button"
        >
          Log Files
        </button>
        <button
          className={page === "github" ? "workflow-button active" : "workflow-button"}
          onClick={() => onSelectPage("github")}
          type="button"
        >
          GitHub Logs
        </button>
        <button
          className={page === "settings" ? "workflow-button active" : "workflow-button"}
          onClick={() => onSelectPage("settings")}
          type="button"
        >
          Settings
        </button>
      </div>

      <section className="tips-card">
        <h3>How to use it</h3>
        <ol>
          {pageCopy.tips.map((tip) => (
            <li key={tip}>{tip}</li>
          ))}
        </ol>
      </section>
    </aside>
  );
}
