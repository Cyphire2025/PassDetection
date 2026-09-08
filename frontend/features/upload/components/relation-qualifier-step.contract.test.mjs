import assert from "node:assert/strict";
import test from "node:test";
import { uploadFlowSource } from "./upload-flow-source.contract-helper.mjs";

test("enabled qualifier flow stays single-passenger and bypasses family mode", () => {
  const disabledCompatibilityBranch = uploadFlowSource.indexOf(
    "if (!relationWithQualifierEnabled)",
  );
  const enabledSingleMode = uploadFlowSource.indexOf(
    'setFlowMode("single")',
    disabledCompatibilityBranch,
  );
  const qualifierStep = uploadFlowSource.indexOf(
    'setStep("QUALIFIER_SELECT")',
    enabledSingleMode,
  );
  const saveChoiceStart = uploadFlowSource.indexOf(
    "const saveQualifierChoice",
  );
  const saveChoiceEnd = uploadFlowSource.indexOf(
    "const selectFamilyMember",
    saveChoiceStart,
  );
  const saveChoice = uploadFlowSource.slice(saveChoiceStart, saveChoiceEnd);

  assert.ok(disabledCompatibilityBranch >= 0);
  assert.ok(enabledSingleMode > disabledCompatibilityBranch);
  assert.ok(qualifierStep > enabledSingleMode);
  assert.match(saveChoice, /setFlowMode\("single"\)/);
  assert.match(saveChoice, /setStep\("METHOD_SELECT"\)/);
  assert.doesNotMatch(uploadFlowSource, /NAME_INPUT/);
  assert.doesNotMatch(saveChoice, /setFlowMode\("family"\)/);
});
