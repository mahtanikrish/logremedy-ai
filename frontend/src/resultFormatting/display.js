export function sentenceCase(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function lowerText(value) {
  return String(value || "").trim().toLowerCase();
}

export function dedupe(items) {
  return items.filter((item, index) => item && items.indexOf(item) === index);
}

export function normalizeSentence(value) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return text[0].toUpperCase() + text.slice(1);
}

export function prettyFixType(value) {
  const formatted = sentenceCase(value);
  return lowerText(formatted).endsWith("fix") ? formatted : `${formatted} Fix`;
}

export function operatorVerificationLabel(status, reason) {
  const text = lowerText(reason);
  if (text.includes("must target an existing file")) {
    return "Blocked By File Targeting Rule";
  }
  if (text.includes("repo not provided")) {
    return "Verification Skipped";
  }
  if (text.includes("repo does not exist")) {
    return "Verification Repo Missing";
  }

  switch (status) {
    case "verified":
      return "Verified";
    case "failed_replay":
      return "Failed In Replay";
    case "rejected_precondition":
      return "Verification Could Not Start";
    case "rejected_policy":
      return "Blocked By Safety Rule";
    case "rejected_grounding":
      return "Blocked By Repo Grounding";
    case "rejected_static":
      return "Blocked By Static Checks";
    case "rejected_adapter_check":
      return "Blocked By Deterministic Check";
    case "rejected_execution":
      return "Execution Check Failed";
    case "inconclusive":
      return "Needs Manual Review";
    default:
      return sentenceCase(status);
  }
}

export function keyLineText(item) {
  const line = String(item?.text || "").replace(/\s+/g, " ").trim();
  return `Line ${item?.lineno ?? "?"}: ${line || "No text captured."}`;
}
