import test from "node:test";
import assert from "node:assert/strict";

import { buildVerificationSection } from "./verification.js";

test("buildVerificationSection hides low-signal verifier internals from the default view", () => {
  const section = buildVerificationSection({
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
        { name: "adapter_check", status: "skipped", reason: "not reached" },
      ],
    },
  });

  assert.equal(section.subheading, "Blocked By File Targeting Rule");
  assert.equal(
    section.groups[0].body,
    "The proposed patch targets run_tests.py, but that file does not exist in the verification repository.",
  );
  assert.deepEqual(section.groups[1].bullets, [
    "Current gate: Policy",
    "Verification rejected by policy",
    "Affected path: run_tests.py",
  ]);
  assert.deepEqual(section.groups[2].bullets, [
    "Preconditions: Passed - verification workspace prepared",
    "File Targeting Rule: Failed - supported benchmark patch must target an existing file: run_tests.py",
  ]);
  assert.deepEqual(section.groups[2].details, [
    "Raw verification status: Rejected Policy",
    "Terminal gate: Policy",
    "Capability summary: verification rejected by policy",
    "Skipped checks: Adapter Check",
  ]);
});
