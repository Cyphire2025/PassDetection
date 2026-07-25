import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./relation-qualifier-step.tsx", import.meta.url),
  "utf8",
);
const uploadFlowSource = readFileSync(
  new URL("./upload-flow.tsx", import.meta.url),
  "utf8",
);

test("qualifier paths remain one accessible radio choice", () => {
  assert.match(source, /role="radiogroup"/);
  assert.equal(source.match(/role="radio"/g)?.length, 2);
  assert.match(source, /aria-checked=\{path === "self"\}/);
  assert.match(source, /aria-checked=\{path === "relation"\}/);
  assert.match(source, /tabIndex=\{path === "relation" \? -1 : 0\}/);
  assert.match(
    source,
    /tabIndex=\{path === "relation" && hasRelationOptions \? 0 : -1\}/,
  );
  assert.match(source, /handleRadioKeyDown/);
  assert.match(source, /"ArrowDown"/);
  assert.match(source, /"ArrowLeft"/);
});

test("stale or unavailable relation options cannot continue", () => {
  assert.match(
    source,
    /const relationIsAllowed = options\.some\(\(option\) => option\.code === relationCode\)/,
  );
  assert.match(source, /path === "relation"\s*&& relationIsAllowed/);
  assert.match(source, /disabled=\{isSaving \|\| !hasRelationOptions\}/);
  assert.match(source, /No eligible relationships are currently available/);
});

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
