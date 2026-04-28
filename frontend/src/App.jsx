import { useEffect, useMemo, useState } from "react";
import { getJson, postFormData, postJson } from "./api";
import { INITIAL_FORM, PAGE_COPY, TAB_ORDER } from "./appConfig";
import GitHubLogForm from "./components/forms/GitHubLogForm";
import LogFileForm from "./components/forms/LogFileForm";
import SettingsForm from "./components/forms/SettingsForm";
import ResultPanel from "./components/ResultPanel";
import WorkflowSidebar from "./components/WorkflowSidebar";
import { emptyResultState, formatResultPayload } from "./resultFormatting";
import { buildSummaryCards } from "./viewModel";

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
  const [settingsInfo, setSettingsInfo] = useState(null);

  const pageCopy = PAGE_COPY[page];
  const summaryCards = useMemo(
    () => buildSummaryCards(page, resultState, settingsInfo),
    [page, resultState, settingsInfo],
  );

  useEffect(() => {
    loadSettings();
  }, []);

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

  function updateSettingsField(field, value) {
    setForm((current) => ({
      ...current,
      settings: {
        ...current.settings,
        [field]: value,
      },
    }));
  }

  async function loadSettings() {
    try {
      const data = await getJson("/api/settings");
      setSettingsInfo(data);
      setForm((current) => ({
        ...current,
        settings: {
          knowledgeBasePath: data.settings?.knowledgeBasePath || "",
          envFilePath: data.settings?.envFilePath || "",
        },
      }));
    } catch (error) {
      setErrorText(error.message);
    }
  }

  async function saveSettings() {
    setIsRunning(true);
    setErrorText("");
    setStatusText("Saving settings...");

    try {
      const data = await postJson("/api/settings", {
        knowledgeBasePath: form.settings.knowledgeBasePath.trim(),
        envFilePath: form.settings.envFilePath.trim(),
      });
      setSettingsInfo(data);
      setStatusText("Settings saved.");
    } catch (error) {
      setErrorText(error.message);
      setStatusText("Settings update failed.");
    } finally {
      setIsRunning(false);
    }
  }

  async function runSynthetic() {
    if (!selectedSyntheticFile) {
      setErrorText("Choose a log file first.");
      return;
    }

    setIsRunning(true);
    setErrorText("");
    setStatusText("Running analysis...");

    try {
      const formData = new FormData();
      formData.append("logFile", selectedSyntheticFile);
      formData.append("repo", form.synthetic.repo.trim());
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
        verifyRepo: form.github.verifyRepo.trim(),
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

  const activeSection = resultState.sections[activeTab];

  function renderActiveForm() {
    if (page === "synthetic") {
      return (
        <LogFileForm
          logName={form.synthetic.logName}
          repo={form.synthetic.repo}
          isRunning={isRunning}
          onFileChange={handleSyntheticFileChange}
          onRepoChange={(value) => updateSyntheticField("repo", value)}
          onSubmit={runSynthetic}
        />
      );
    }

    if (page === "github") {
      return (
        <GitHubLogForm
          repoName={form.github.repoName}
          runId={form.github.runId}
          verifyRepo={form.github.verifyRepo}
          isRunning={isRunning}
          onRepoNameChange={(value) => updateGithubField("repoName", value)}
          onRunIdChange={(value) => updateGithubField("runId", value)}
          onVerifyRepoChange={(value) => updateGithubField("verifyRepo", value)}
          onSubmit={runGithub}
        />
      );
    }

    return (
      <SettingsForm
        knowledgeBasePath={form.settings.knowledgeBasePath}
        envFilePath={form.settings.envFilePath}
        isRunning={isRunning}
        onKnowledgeBasePathChange={(value) => updateSettingsField("knowledgeBasePath", value)}
        onEnvFilePathChange={(value) => updateSettingsField("envFilePath", value)}
        onReload={loadSettings}
        onSave={saveSettings}
      />
    );
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>Log Clinic</h1>
          <p className="subtitle">
            AI-powered GitHub Actions log analysis and remediation with verification-gated fixes.
          </p>
        </div>
      </header>

      <main className="workspace">
        <WorkflowSidebar page={page} onSelectPage={setPage} pageCopy={pageCopy} />

        <section className="left-panel">
          <div className="hero-card">
            <h2>{pageCopy.title}</h2>
            <p>{pageCopy.description}</p>
          </div>

          {renderActiveForm()}
        </section>

        <ResultPanel
          page={page}
          statusText={statusText}
          summaryCards={summaryCards}
          settingsInfo={settingsInfo}
          form={form}
          activeTab={activeTab}
          activeSection={activeSection}
          resultState={resultState}
          tabs={TAB_ORDER}
          onSelectTab={setActiveTab}
          errorText={errorText}
        />
      </main>
    </div>
  );
}

export default App;
