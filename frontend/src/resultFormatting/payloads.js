import { keyLineText, operatorVerificationLabel, prettyFixType, sentenceCase } from "./display.js";
import { buildVerificationSection } from "./verification.js";

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

export function emptyResultState() {
  return {
    summary: {
      failureClass: "Waiting for analysis",
      fixType: "Waiting for analysis",
      verification: "Waiting for analysis",
    },
    sections: {
      rca: {
        headline: "What failed?",
        subheading: "No analysis yet",
        groups: [
          {
            title: "Ready for a run",
            body: "Use the controls on the left, then run a log file or GitHub case to populate this report view.",
            bullets: [
              "RCA will explain what likely failed and why.",
              "Remediation will summarise the proposed fix and assumptions.",
              "Verification will show whether the fix can be trusted.",
            ],
          },
        ],
      },
      remediation: {
        headline: "What should change?",
        subheading: "No analysis yet",
        groups: [
          {
            title: "Ready for a run",
            body: "Use the controls on the left, then run a log file or GitHub case to populate this report view.",
            bullets: [
              "The recommended change will appear here once the analysis completes.",
            ],
          },
        ],
      },
      verification: {
        headline: "Can this fix be trusted?",
        subheading: "No analysis yet",
        groups: [
          {
            title: "Ready for a run",
            body: "Verification output will appear here after the backend completes the run.",
            bullets: [
              "The default view will focus on the decision, not the raw verifier internals.",
            ],
          },
        ],
      },
      rawLog: "No raw log yet.\nRun a log file or GitHub case to populate this panel.",
    },
  };
}

export function formatResultPayload(result, rawLog) {
  const rca = result?.rca || {};
  const remediation = result?.remediation || {};
  const verification = result?.verification || {};
  const verificationSection = buildVerificationSection(verification);
  const remediationGroups = [
    {
      title: "Recommended Change",
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
      fixType: prettyFixType(remediation.fix_type),
      verification: operatorVerificationLabel(verification.status, verification.reason),
    },
    sections: {
      rca: {
        headline: "What failed?",
        subheading: sentenceCase(rca.failure_class),
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
        headline: "What should change?",
        subheading: prettyFixType(remediation.fix_type),
        groups: remediationGroups,
      },
      verification: verificationSection,
      rawLog: rawLog || "No raw log captured for this run.",
    },
  };
}
