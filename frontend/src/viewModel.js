export function buildSummaryCards(page, resultState, settingsInfo) {
  if (page === "settings") {
    return [
      {
        label: "Knowledge Base",
        value: settingsInfo?.knowledgeBase?.configured
          ? settingsInfo?.knowledgeBase?.docCount
            ? `${settingsInfo.knowledgeBase.docCount} docs`
            : "Configured"
          : "Default",
      },
      {
        label: "GitHub Token",
        value: settingsInfo?.githubToken?.present
          ? settingsInfo.githubToken.source === "env_file"
            ? "Loaded from env file"
            : "Loaded from environment"
          : "Not available",
      },
      {
        label: "Settings File",
        value: settingsInfo?.settingsFilePath || "Not saved yet",
      },
    ];
  }

  return [
    { label: "Failure Class", value: resultState.summary.failureClass },
    { label: "Fix Type", value: resultState.summary.fixType },
    { label: "Verification", value: resultState.summary.verification },
  ];
}
