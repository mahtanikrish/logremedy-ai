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

test("formatResultPayload avoids duplicated fix wording in remediation headline", () => {
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
      verification: { status: "verified", reason: "all checks passed", evidence: {} },
    },
    "",
  );

  assert.equal(result.sections.remediation.headline, "What should change?");
  assert.equal(result.sections.remediation.subheading, "Code Fix");
});

test("formatResultPayload keeps verification output compact and drops skipped gates", () => {
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
        status: "rejected_policy",
        reason: "safety: supported benchmark patch must target an existing file: run_tests.py",
        evidence: {
          gate: "policy",
          path: "run_tests.py",
          profile: "strict",
          capability: {
            summary: "verification rejected by policy",
            selected_validator: "none",
            execution_mode: "deterministic",
          },
          gates: [
            { name: "preconditions", status: "passed", reason: "verification workspace prepared" },
            { name: "policy", status: "failed", reason: "supported benchmark patch must target an existing file: run_tests.py" },
            { name: "static", status: "skipped", reason: "not reached" },
          ],
        },
      },
    },
    "",
  );

  const groups = result.sections.verification.groups;
  assert.equal(groups[0].title, "Verification Outcome");
  assert.equal(groups[0].body, "The proposed patch targets run_tests.py, but that file does not exist in the verification repository.");
  assert.equal(groups[1].title, "Key Facts");
  assert.deepEqual(groups[1].bullets, [
    "Current gate: Policy",
    "Verification rejected by policy",
    "Affected path: run_tests.py",
  ]);
  assert.equal(groups[2].title, "Reached Checks");
  assert.deepEqual(groups[2].bullets, [
    "Preconditions: Passed - verification workspace prepared",
    "File Targeting Rule: Failed - supported benchmark patch must target an existing file: run_tests.py",
  ]);
  assert.deepEqual(groups[2].details, [
    "Raw verification status: Rejected Policy",
    "Terminal gate: Policy",
    "Capability summary: verification rejected by policy",
    "Skipped checks: Static",
  ]);
});

test("formatResultPayload keeps remediation cards in operator-facing order", () => {
  const result = formatResultPayload(
    {
      rca: { failure_class: "test_failure", root_causes: [] },
      remediation: {
        fix_type: "code_fix",
        risk_level: "low",
        patches: [{ path: "run_tests.py", diff: "--- a\n+++ b\n" }],
        commands: [],
        guidance: ["Confirm the renamed target matches the real test file."],
        assumptions: ["run_tests.py should already exist in the repo."],
        rollback: ["Revert the patch if the target file mapping is wrong."],
      },
      verification: { status: "verified", reason: "all checks passed", evidence: {} },
    },
    "",
  );

  assert.deepEqual(
    result.sections.remediation.groups.map((group) => group.title),
    ["Recommended Change", "Developer Guidance", "Assumptions", "Rollback Plan"],
  );
});
