function ResultGroupCard({ group }) {
  return (
    <article className="report-card" key={group.title}>
      <h4>{group.title}</h4>
      <p>{group.body}</p>
      {group.bullets?.length > 0 && (
        <div className="bullet-panel">
          {group.bullets.map((bullet, index) => (
            <div className="bullet-line" key={`${group.title}-${index}-${bullet}`}>
              <span className="bullet-mark">-</span>
              <span>{bullet}</span>
            </div>
          ))}
        </div>
      )}
      {group.collapsible && group.details?.length > 0 && (
        <details className="report-disclosure">
          <summary>{group.detailsLabel || "Technical details"}</summary>
          <div className="bullet-panel disclosure-panel">
            {group.details.map((detail, index) => (
              <div className="bullet-line" key={`${group.title}-detail-${index}-${detail}`}>
                <span className="bullet-mark">-</span>
                <span>{detail}</span>
              </div>
            ))}
          </div>
        </details>
      )}
    </article>
  );
}

export default function AnalysisReport({ activeTab, activeSection, rawLog, tabs, onSelectTab }) {
  return (
    <>
      <div className="tab-row">
        {tabs.map((tab) => (
          <button
            className={activeTab === tab.key ? "tab-button active" : "tab-button"}
            key={tab.key}
            onClick={() => onSelectTab(tab.key)}
            type="button"
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="result-surface">
        {activeTab === "rawLog" ? (
          <div className="report-view">
            <article className="report-card raw-log-only-card">
              <div className="raw-log-panel">
                <pre className="raw-log-text">{rawLog}</pre>
              </div>
            </article>
          </div>
        ) : (
          <div className="report-view">
            <section className="report-hero">
              <h3>{activeSection.headline}</h3>
              {activeSection.subheading ? <p className="report-kicker">{activeSection.subheading}</p> : null}
              <div className={`accent-bar accent-${activeTab}`} />
            </section>

            {activeSection.groups.map((group) => (
              <ResultGroupCard group={group} key={group.title} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
