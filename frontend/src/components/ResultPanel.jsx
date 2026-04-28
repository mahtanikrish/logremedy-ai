import AnalysisReport from "./AnalysisReport";
import SettingsInsights from "./SettingsInsights";

export default function ResultPanel({
  page,
  statusText,
  summaryCards,
  settingsInfo,
  form,
  activeTab,
  activeSection,
  resultState,
  tabs,
  onSelectTab,
  errorText,
}) {
  return (
    <section className="result-panel">
      <div className="status-banner">{statusText}</div>

      <div className="summary-grid">
        {summaryCards.map((card) => (
          <article className="summary-card" key={card.label}>
            <span>{card.label}</span>
            <strong>{card.value}</strong>
          </article>
        ))}
      </div>

      {page === "settings" ? (
        <SettingsInsights settingsInfo={settingsInfo} form={form} />
      ) : (
        <AnalysisReport
          activeTab={activeTab}
          activeSection={activeSection}
          rawLog={resultState.sections.rawLog}
          tabs={tabs}
          onSelectTab={onSelectTab}
        />
      )}

      {errorText ? <div className="error-banner">{errorText}</div> : null}
    </section>
  );
}
