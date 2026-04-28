import { dedupe, lowerText, normalizeSentence, operatorVerificationLabel, sentenceCase } from "./display.js";

function verificationWasSkipped(verification) {
  const reason = lowerText(verification?.reason);
  const summary = lowerText(verification?.evidence?.capability?.summary);
  return reason.startsWith("verification skipped:")
    || summary.startsWith("verification skipped");
}

function fileTargetPath(verification) {
  if (verification?.evidence?.path) {
    return String(verification.evidence.path);
  }
  const match = String(verification?.reason || "").match(/existing file:\s*([^\s]+)/i);
  return match ? match[1] : "";
}

export function operatorVerificationReason(verification) {
  const reason = String(verification?.reason || "").trim();
  if (!reason) {
    return "No verification explanation returned.";
  }

  const text = lowerText(reason);
  if (text.includes("must target an existing file")) {
    const path = fileTargetPath(verification);
    return path
      ? `The proposed patch targets ${path}, but that file does not exist in the verification repository.`
      : "The proposed patch targets a file that does not exist in the verification repository.";
  }
  if (text.startsWith("verification skipped: repo not provided")) {
    return "Verification was skipped because no local verification repository was provided.";
  }
  if (text.startsWith("verification skipped: repo does not exist")) {
    return "Verification was skipped because the supplied repository path does not exist.";
  }
  if (text.startsWith("safety:")) {
    return normalizeSentence(reason.slice("safety:".length).trim());
  }
  return normalizeSentence(reason);
}

function verificationOverviewBullets(verification) {
  const bullets = [];
  const gate = String(verification?.evidence?.gate || "").trim();
  const capability = verification?.evidence?.capability || {};
  const path = fileTargetPath(verification);
  const summary = String(capability.summary || "").trim();
  const validator = String(capability.selected_validator || "").trim();
  const executionMode = String(capability.execution_mode || "").trim();

  if (gate) {
    bullets.push(`Current gate: ${sentenceCase(gate)}`);
  }
  if (summary && lowerText(summary) !== lowerText(verification?.reason)) {
    bullets.push(normalizeSentence(summary));
  }
  if (validator && validator !== "none") {
    bullets.push(`Validator used: ${sentenceCase(validator)}`);
  }
  if (executionMode && executionMode !== "deterministic") {
    bullets.push(`Execution mode: ${sentenceCase(executionMode)}`);
  }
  if (path) {
    bullets.push(`Affected path: ${path}`);
  }

  return dedupe(bullets).slice(0, 4);
}

function userFacingGateName(name, reason) {
  const loweredReason = lowerText(reason);
  if (name === "policy" && loweredReason.includes("must target an existing file")) {
    return "File Targeting Rule";
  }
  return sentenceCase(name || "unknown");
}

function gateResultBullets(verification) {
  const gates = Array.isArray(verification?.evidence?.gates) ? verification.evidence.gates : [];
  return gates
    .filter((gate) => gate && gate.status !== "skipped")
    .map((gate) => {
      const name = userFacingGateName(gate.name, gate.reason);
      const status = sentenceCase(gate.status || "unknown");
      const reason = String(gate.reason || "").replace(/^safety:\s*/i, "").trim();
      return reason ? `${name}: ${status} - ${reason}` : `${name}: ${status}`;
    });
}

function technicalDetailBullets(verification) {
  const evidence = verification?.evidence || {};
  const capability = evidence.capability || {};
  const gates = Array.isArray(evidence.gates) ? evidence.gates : [];
  const skipped = gates
    .filter((gate) => gate && gate.status === "skipped")
    .map((gate) => sentenceCase(gate.name || "unknown"));

  const details = [];
  if (verification?.status) {
    details.push(`Raw verification status: ${sentenceCase(verification.status)}`);
  }
  if (evidence.gate) {
    details.push(`Terminal gate: ${sentenceCase(evidence.gate)}`);
  }
  if (capability.selected_validator && capability.selected_validator !== "none") {
    details.push(`Selected validator: ${capability.selected_validator}`);
  }
  if (capability.execution_mode && capability.execution_mode !== "deterministic") {
    details.push(`Execution mode: ${capability.execution_mode}`);
  }
  if (capability.summary) {
    details.push(`Capability summary: ${capability.summary}`);
  }
  if (skipped.length) {
    details.push(`Skipped checks: ${skipped.join(", ")}`);
  }
  return details;
}

export function buildVerificationSection(verification) {
  const headline = "Can this fix be trusted?";
  const subheading = operatorVerificationLabel(verification?.status, verification?.reason);

  if (verificationWasSkipped(verification)) {
    return {
      headline,
      subheading,
      groups: [
        {
          title: "Verification Outcome",
          body: operatorVerificationReason(verification),
          bullets: [],
        },
        {
          title: "Evidence",
          body: "Verification was skipped, so no evidence was collected.",
          bullets: [],
        },
      ],
    };
  }

  const overview = verificationOverviewBullets(verification);
  const gateBullets = gateResultBullets(verification);
  const technicalDetails = technicalDetailBullets(verification);

  return {
    headline,
    subheading,
    groups: [
      {
        title: "Verification Outcome",
        body: operatorVerificationReason(verification),
        bullets: [],
      },
      {
        title: "Key Facts",
        body: "The essential signals you should use to decide whether to trust this fix.",
        bullets: overview,
      },
      {
        title: "Reached Checks",
        body: "Checks that actually ran before verification stopped or completed.",
        bullets: gateBullets,
        collapsible: technicalDetails.length > 0,
        detailsLabel: "Technical details",
        details: technicalDetails,
      },
    ],
  };
}
