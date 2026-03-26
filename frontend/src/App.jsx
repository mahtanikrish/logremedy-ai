import { useMemo, useState } from "react";
import { postFormData, postJson } from "./api";
import { emptyResultState, formatResultPayload } from "./resultFormatting";

const INITIAL_FORM = {
  synthetic: {
    logName: "",
    rawLogText: "",
    repo: "",
  },
  github: {
    repoName: "",
    runId: "",
    verifyRepo: "",
  },
};

const PAGE_COPY = {
  synthetic: {
    title: "Synthetic Logs",
    description:
      "Use a local failure log from the synthetic dataset and run the full LLM pipeline against a chosen verification repository.",
    tips: [
      "Choose a local .log file.",
      "Check the repo path.",
      "Run the analysis.",
    ],
  },
  github: {
    title: "GitHub Logs",
    description:
      "Fetch a recent failed GitHub Actions run, combine its logs, and analyze it against a local clone for verification.",
    tips: [
      "Enter owner/name.",
      "Leave run ID blank for the latest failed run.",
      "Point verification to a local clone.",
    ],
  },
};

const TAB_ORDER = [
  { key: "rca", label: "RCA" },
  { key: "remediation", label: "Remediation" },
  { key: "verification", label: "Verification" },
  { key: "rawLog", label: "Raw Log" },
];

function App() {
  const [page, setPage] = useState("synthetic");
  const [activeTab, setActiveTab] = useState("rca");
  const [model] = useState("gpt-4o-mini");
  const [form, setForm] = useState(INITIAL_FORM);
  const [statusText, setStatusText] = useState("Ready.");
  const [isRunning, setIsRunning] = useState(false);
  const [errorText, setErrorText] = useState("");
  const [resultState, setResultState] = useState(emptyResultState());
  const [selectedSyntheticFile, setSelectedSyntheticFile] = useState(null);

  const pageCopy = PAGE_COPY[page];
  const summaryCards = useMemo(
    () => [
      { label: "Failure Class", value: resultState.summary.failureClass },
      { label: "Fix Type", value: resultState.summary.fixType },
      { label: "Verification", value: resultState.summary.verification },
    ],
    [resultState],
  );

  function updateSyntheticField(field, value) {
    setForm((current) => ({
      ...current,
      synthetic: {
        ...current.synthetic,
        [field]: value,
      },
    }));
  }

  async function handleSyntheticFileChange(event) {
    const file = event.target.files?.[0];
    if (!file) {
      setSelectedSyntheticFile(null);
      updateSyntheticField("logName", "");
      return;
    }
    setSelectedSyntheticFile(file);
    setForm((current) => ({
      ...current,
      synthetic: {
        ...current.synthetic,
        logName: file.name,
        rawLogText: "",
      },
    }));
    setErrorText("");
    setStatusText(`Loaded local log file: ${file.name}`);
  }

  function updateGithubField(field, value) {
    setForm((current) => ({
      ...current,
      github: {
        ...current.github,
        [field]: value,
      },
    }));
  }

  async function runSynthetic() {
    if (!selectedSyntheticFile) {
      setErrorText("Choose a synthetic log file first.");
      return;
    }

    setIsRunning(true);
    setErrorText("");
    setStatusText("Running analysis...");

    try {
      const formData = new FormData();
      formData.append("logFile", selectedSyntheticFile);
      formData.append("repo", form.synthetic.repo || ".");
      formData.append("model", model);

      const data = await postFormData("/api/analyze/synthetic", formData);
      setResultState(formatResultPayload(data.result, data.rawLog));
      setStatusText(data.statusText);
      setActiveTab("rca");
    } catch (error) {
      setErrorText(error.message);
      setStatusText("Analysis failed.");
    } finally {
      setIsRunning(false);
    }
  }

  async function runGithub() {
    if (!form.github.repoName.trim()) {
      setErrorText("Enter a GitHub repo in owner/name form.");
      return;
    }

    setIsRunning(true);
    setErrorText("");
    setStatusText("Running analysis...");

    try {
      const data = await postJson("/api/analyze/github", {
        repoName: form.github.repoName,
        runId: form.github.runId,
        verifyRepo: form.github.verifyRepo || ".",
        model,
      });
      setResultState(formatResultPayload(data.result, data.rawLog));
      setStatusText(data.statusText);
      setActiveTab("rca");
    } catch (error) {
      setErrorText(error.message);
      setStatusText("Analysis failed.");
    } finally {
      setIsRunning(false);
    }
  }

  function loadSampleSynthetic() {
    setPage("synthetic");
    setForm((current) => ({
      ...current,
      synthetic: {
        logName: "log_1_20251121-164424.log",
        rawLogText: "",
        repo: ".",
      },
    }));
    setSelectedSyntheticFile(null);
    setStatusText("Choose a local log file to run synthetic analysis in the web app.");
  }

  function loadDemoGithub() {
    setPage("github");
    setForm((current) => ({
      ...current,
      github: {
        repoName: "mahtanikrish/actions-log-generator",
        runId: "",
        verifyRepo: ".",
      },
    }));
    setStatusText("Loaded demo GitHub case.");
  }

  const activeSection = resultState.sections[activeTab];

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Final year project demo</p>
          <h1>GHA Remediator</h1>
          <p className="subtitle">
            AI-powered GitHub Actions log analysis and remediation with verification-gated fixes.
          </p>
        </div>
      </header>

      <main className="workspace">
        <aside className="sidebar">
          <h2>Workflows</h2>

          <div className="workflow-switcher">
            <button
              className={page === "synthetic" ? "workflow-button active" : "workflow-button"}
              onClick={() => setPage("synthetic")}
              type="button"
            >
              Synthetic Logs
            </button>
            <button
              className={page === "github" ? "workflow-button active" : "workflow-button"}
              onClick={() => setPage("github")}
              type="button"
            >
              GitHub Logs
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

        <section className="left-panel">
          <div className="hero-card">
            <h2>{pageCopy.title}</h2>
            <p>{pageCopy.description}</p>
          </div>

          {page === "synthetic" ? (
            <div className="form-card">
              <label className="field">
                <span>Log file</span>
                <label className="upload-field" htmlFor="synthetic-log-file">
                  <input
                    id="synthetic-log-file"
                    type="file"
                    accept=".log,.txt,.json,.out,.text"
                    onChange={handleSyntheticFileChange}
                  />
                  <span className="upload-button">Choose Log File</span>
                  <span className="upload-name">
                    {form.synthetic.logName || "No file selected"}
                  </span>
                </label>
                <small>Select a local `.log` file and the browser will upload its contents for analysis.</small>
              </label>

              <label className="field">
                <span>Verification repo</span>
                <input
                  value={form.synthetic.repo}
                  onChange={(event) => updateSyntheticField("repo", event.target.value)}
                  placeholder="."
                />
                <small>This local repo path is used by the verification checks.</small>
              </label>

              <div className="actions">
                <button className="secondary-action" onClick={loadSampleSynthetic} type="button">
                  Load Sample Case
                </button>
                <button className="primary-action" onClick={runSynthetic} disabled={isRunning} type="button">
                  {isRunning ? "Running..." : "Run Synthetic Analysis"}
                </button>
              </div>
            </div>
          ) : (
            <div className="form-card">
              <label className="field">
                <span>GitHub repo (owner/name)</span>
                <input
                  value={form.github.repoName}
                  onChange={(event) => updateGithubField("repoName", event.target.value)}
                  placeholder="owner/name"
                />
                <small>Example: mahtanikrish/actions-log-generator</small>
              </label>

              <label className="field">
                <span>Run ID</span>
                <input
                  value={form.github.runId}
                  onChange={(event) => updateGithubField("runId", event.target.value)}
                  placeholder="Optional"
                />
                <small>Leave blank to use the latest failed run with downloadable logs.</small>
              </label>

              <label className="field">
                <span>Verification repo</span>
                <input
                  value={form.github.verifyRepo}
                  onChange={(event) => updateGithubField("verifyRepo", event.target.value)}
                  placeholder="."
                />
                <small>Use a local clone of the same repo if you want meaningful verification results.</small>
              </label>

              <div className="actions">
                <button className="secondary-action" onClick={loadDemoGithub} type="button">
                  Load Demo Repo
                </button>
                <button className="primary-action" onClick={runGithub} disabled={isRunning} type="button">
                  {isRunning ? "Running..." : "Run GitHub Analysis"}
                </button>
              </div>
            </div>
          )}
        </section>

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

          <div className="tab-row">
            {TAB_ORDER.map((tab) => (
              <button
                className={activeTab === tab.key ? "tab-button active" : "tab-button"}
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
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
                    <pre className="raw-log-text">{resultState.sections.rawLog}</pre>
                  </div>
                </article>
              </div>
            ) : (
              <div className="report-view">
                <section className="report-hero">
                  <h3>{activeSection.headline}</h3>
                  <div className={`accent-bar accent-${activeTab}`} />
                </section>

                {activeSection.groups.map((group) => (
                  <article className="report-card" key={group.title}>
                    <h4>{group.title}</h4>
                    <p>{group.body}</p>
                    {group.bullets.length > 0 && (
                      <div className="bullet-panel">
                        {group.bullets.map((bullet) => (
                          <div className="bullet-line" key={`${group.title}-${bullet}`}>
                            <span className="bullet-mark">-</span>
                            <span>{bullet}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </div>

          {errorText ? <div className="error-banner">{errorText}</div> : null}
        </section>
      </main>
    </div>
  );
}

export default App;
