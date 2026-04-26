import test from "node:test";
import assert from "node:assert/strict";

import { formatResultPayload } from "./resultFormatting.js";

test("formatResultPayload surfaces patch summaries before commands or fallback text", () => {
  const result = formatResultPayload(
    {
      rca: { failure_class: "test_failure", root_causes: [] },
      remediation: {
        fix_type: "rename_class",
        risk_level: "low",
        patches: [{ path: "test/test_extractor.py", diff: "--- a\n+++ b\n" }],
        commands: [],
        guidance: ["Inspect the class name mismatch."],
        assumptions: [],
        rollback: [],
      },
      verification: { status: "inconclusive", reason: "", evidence: {} },
    },
    "",
  );

  const groups = result.sections.remediation.groups;
  assert.deepEqual(groups[0].bullets, ["Review the proposed patch for test/test_extractor.py."]);
  assert.equal(groups[1].title, "Developer Guidance");
  assert.deepEqual(groups[1].bullets, ["Inspect the class name mismatch."]);
});

test("formatResultPayload uses guidance when commands and patches are absent", () => {
  const result = formatResultPayload(
    {
      rca: { failure_class: "test_failure", root_causes: [] },
      remediation: {
        fix_type: "test_reproduce_and_hint",
        risk_level: "low",
        patches: [],
        commands: [],
        guidance: ["Inspect the failing assertion.", "Rerun the failing test target."],
        assumptions: [],
        rollback: [],
      },
      verification: { status: "inconclusive", reason: "", evidence: {} },
    },
    "",
  );

  const groups = result.sections.remediation.groups;
  assert.deepEqual(groups[0].bullets, [
    "Inspect the failing assertion.",
    "Rerun the failing test target.",
  ]);
});

test("formatResultPayload leaves skipped verification evidence empty", () => {
  const result = formatResultPayload(
    {
      rca: { failure_class: "test_failure", root_causes: [] },
      remediation: {
        fix_type: "code_fix",
        risk_level: "low",
        patches: [],
        commands: [],
        guidance: [],
        assumptions: [],
        rollback: [],
      },
      verification: {
        status: "inconclusive",
        reason: "verification skipped: repo not provided",
        evidence: {
          gate: "preconditions",
          capability: {
            summary: "verification skipped because repo was not provided",
          },
        },
      },
    },
    "",
  );

  const groups = result.sections.verification.groups;
  assert.equal(groups[1].title, "Evidence");
  assert.equal(groups[1].body, "Verification was skipped, so no evidence was collected.");
  assert.deepEqual(groups[1].bullets, []);
});
