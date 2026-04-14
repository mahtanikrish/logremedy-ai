function sentenceCase(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatInline(value) {
  if (Array.isArray(value)) {
    if (!value.length) {
      return "None";
    }
    if (value.every((item) => item && typeof item === "object")) {
      return value.map((item) => `{ ${formatObject(item)} }`).join("; ");
    }
    return value.join(", ");
  }
  if (value && typeof value === "object") {
    return formatObject(value);
  }
  return String(value);
}

function formatObject(value) {
  return Object.entries(value || {})
    .map(([innerKey, innerValue]) => `${sentenceCase(innerKey)}: ${formatInline(innerValue)}`)
    .join(", ");
}

function flattenEvidence(evidence) {
  return Object.entries(evidence || {}).flatMap(([key, value]) => {
    if (Array.isArray(value)) {
      if (!value.length) {
        return [`${sentenceCase(key)}: None`];
      }
      if (value.every((item) => item && typeof item === "object")) {
        return value.map((item) => `${sentenceCase(key)}: ${formatObject(item)}`);
      }
      return [`${sentenceCase(key)}: ${value.join(", ")}`];
    }
    if (value && typeof value === "object") {
      const rendered = formatObject(value);
      return [`${sentenceCase(key)}: ${rendered || "None"}`];
    }
    return [`${sentenceCase(key)}: ${String(value)}`];
  });
}

function keyLineText(item) {
  const line = String(item?.text || "").replace(/\s+/g, " ").trim();
  return `Line ${item?.lineno ?? "?"}: ${line || "No text captured."}`;
}

export function emptyResultState() {
  return {
    summary: {
      failureClass: "Waiting for analysis",
      fixType: "Waiting for analysis",
      verification: "Waiting for analysis",
    },
    sections: {
      rca: {
        headline: "No analysis yet",
        groups: [
          {
            title: "Ready for a run",
            body: "Use the controls on the left, then run a synthetic or GitHub case to populate this report view.",
            bullets: [
              "RCA will explain what likely failed and why.",
              "Remediation will summarise the proposed fix and assumptions.",
              "Verification will show the current gate result and supporting evidence.",
            ],
          },
        ],
      },
      remediation: {
        headline: "No analysis yet",
        groups: [
          {
            title: "Ready for a run",
            body: "Use the controls on the left, then run a synthetic or GitHub case to populate this report view.",
            bullets: [
              "Proposed changes will appear here once the analysis completes.",
            ],
          },
        ],
      },
      verification: {
        headline: "No analysis yet",
        groups: [
          {
            title: "Ready for a run",
            body: "Verification output will appear here after the backend completes the run.",
            bullets: [
              "Current gate status and evidence will be shown here.",
            ],
          },
        ],
      },
      rawLog: "No raw log yet.\nRun a synthetic or GitHub case to populate this panel.",
    },
  };
}

export function formatResultPayload(result, rawLog) {
  const rca = result?.rca || {};
  const remediation = result?.remediation || {};
  const verification = result?.verification || {};

  return {
    summary: {
      failureClass: sentenceCase(rca.failure_class),
      fixType: sentenceCase(remediation.fix_type),
      verification: sentenceCase(verification.status),
    },
    sections: {
      rca: {
        headline: sentenceCase(rca.failure_class),
        groups: [
          {
            title: "Root Cause Summary",
            body: "Likely causes identified from the failed run.",
            bullets: rca.root_causes?.length ? rca.root_causes : ["No root cause explanation returned."],
          },
          {
            title: "Supporting Log Lines",
            body: "Most relevant lines pulled from the failing log.",
            bullets: rca.key_lines?.length ? rca.key_lines.map(keyLineText) : ["No supporting lines were extracted."],
          },
        ],
      },
      remediation: {
        headline: `${sentenceCase(remediation.fix_type)} fix`,
        groups: [
          {
            title: "Proposed Change",
            body: `Risk level: ${sentenceCase(remediation.risk_level)}`,
            bullets: remediation.commands?.length ? remediation.commands : ["No concrete remediation commands were returned."],
          },
          {
            title: "Assumptions",
            body: "Conditions that need to hold for the proposed fix to be valid.",
            bullets: remediation.assumptions?.length ? remediation.assumptions : ["No assumptions were listed."],
          },
          {
            title: "Rollback Plan",
            body: "How to safely reverse the suggested change.",
            bullets: remediation.rollback?.length ? remediation.rollback : ["No rollback steps were provided."],
          },
        ],
      },
      verification: {
        headline: sentenceCase(verification.status),
        groups: [
          {
            title: "Verification Outcome",
            body: verification.reason || "No verification explanation returned.",
            bullets: [],
          },
          {
            title: "Evidence",
            body: "Signals collected from the current verification stage.",
            bullets: flattenEvidence(verification.evidence).length
              ? flattenEvidence(verification.evidence)
              : ["No verification evidence was returned."],
          },
        ],
      },
      rawLog: rawLog || "No raw log captured for this run.",
    },
  };
}
