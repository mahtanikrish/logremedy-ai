export const INITIAL_FORM = {
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
  settings: {
    knowledgeBasePath: "",
    envFilePath: "",
  },
};

export const PAGE_COPY = {
  synthetic: {
    title: "Log Files",
    description:
      "Upload a raw failure log file and run the full analysis pipeline. Add a verification repository only when you have the matching local checkout.",
    tips: [
      "Choose a local .log file.",
      "Leave the repo path blank to skip verification.",
      "Run the analysis.",
    ],
  },
  github: {
    title: "GitHub Logs",
    description:
      "Fetch a recent failed GitHub Actions run, combine its logs, and analyze it. Add a local clone only when you want verification.",
    tips: [
      "Enter owner/name.",
      "Leave run ID blank for the latest failed run.",
      "Leave verification blank to skip repo-based checks.",
    ],
  },
  settings: {
    title: "Settings",
    description:
      "Configure the retrieval knowledge base and the optional env file used to resolve GitHub credentials.",
    tips: [
      "Leave the knowledge base path blank to use the built-in defaults.",
      "Set an env file path if you want the app to read GITHUB_TOKEN automatically.",
      "Save settings before running analyses.",
    ],
  },
};

export const TAB_ORDER = [
  { key: "rca", label: "RCA" },
  { key: "remediation", label: "Remediation" },
  { key: "verification", label: "Verification" },
  { key: "rawLog", label: "Raw Log" },
];
