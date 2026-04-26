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

function summarizePatch(patch) {
  const path = String(patch?.path || "").trim() || "unknown file";
  return `Review the proposed patch for ${path}.`;
}

function proposedChangeBullets(remediation) {
  if (remediation.patches?.length) {
    return remediation.patches.map(summarizePatch);
  }
  if (remediation.commands?.length) {
    return remediation.commands;
  }
  if (remediation.guidance?.length) {
    return remediation.guidance;
  }
  return ["No concrete remediation commands were returned."];
}

function verificationWasSkipped(verification) {
  const reason = String(verification?.reason || "").toLowerCase();
  const summary = String(verification?.evidence?.capability?.summary || "").toLowerCase();
  return reason.startsWith("verification skipped:")
    || summary.startsWith("verification skipped");
}

function verificationEvidenceGroup(verification) {
  if (verificationWasSkipped(verification)) {
    return {
      title: "Evidence",
      body: "Verification was skipped, so no evidence was collected.",
      bullets: [],
    };
  }

  const bullets = flattenEvidence(verification.evidence);
  return {
    title: "Evidence",
    body: "Signals collected from the current verification stage.",
    bullets,
  };
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
  const remediationGroups = [
    {
      title: "Proposed Change",
      body: `Risk level: ${sentenceCase(remediation.risk_level)}`,
      bullets: proposedChangeBullets(remediation),
    },
  ];

  if (remediation.guidance?.length && (remediation.patches?.length || remediation.commands?.length)) {
    remediationGroups.push({
      title: "Developer Guidance",
      body: "Concrete checks to help a developer inspect and complete the fix safely.",
      bullets: remediation.guidance,
    });
  }

  remediationGroups.push(
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
  );

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
        groups: remediationGroups,
      },
      verification: {
        headline: sentenceCase(verification.status),
        groups: [
          {
            title: "Verification Outcome",
            body: verification.reason || "No verification explanation returned.",
            bullets: [],
          },
          verificationEvidenceGroup(verification),
        ],
      },
      rawLog: rawLog || "No raw log captured for this run.",
    },
  };
}
