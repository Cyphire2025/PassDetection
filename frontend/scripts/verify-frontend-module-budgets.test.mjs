import assert from "node:assert/strict";
import test from "node:test";
import {
  countPhysicalLines,
  evaluateFrontendModuleBudgets,
  frontendModuleBudgets,
  maxFunctionCyclomaticComplexity,
} from "./verify-frontend-module-budgets.mjs";

test("decomposed workflow facades and every extracted owner have reduced budgets", () => {
  const byPath = new Map(frontendModuleBudgets.map((budget) => [budget.path, budget]));
  assert.ok(byPath.get("features/passports/components/passport-group-detail.tsx").maximumLines <= 50);
  assert.ok(byPath.get("features/email-integrations/components/message-activity-page.tsx").maximumLines <= 350);
  for (const name of [
    "passport-group-bindings.tsx", "passport-group-dialogs.tsx", "passport-group-header-panel.tsx",
    "passport-group-import-panel.tsx", "passport-group-model.tsx", "passport-group-overview-panel.tsx",
    "passport-group-roster-panel.tsx", "passport-group-selection-toolbar.tsx", "use-passport-group-controller.tsx",
  ]) {
    const budget = byPath.get(`features/passports/components/${name}`);
    assert.ok(budget, `Missing budget for ${name}`);
    assert.ok(budget.maximumLines <= 750);
    assert.ok(budget.maximumFunctionComplexity <= 50);
  }
  for (const name of [
    "message-activity-model.ts", "message-deadline-decisions.tsx", "message-draft-editor.tsx",
    "message-intelligence-brief.tsx", "message-intelligence-feedback.tsx",
    "message-proposal-decisions.tsx", "use-message-feedback-controller.ts",
  ]) {
    const budget = byPath.get(`features/email-integrations/components/${name}`);
    assert.ok(budget, `Missing budget for ${name}`);
    assert.ok(budget.maximumLines <= 550);
    assert.ok(budget.maximumFunctionComplexity <= 50);
  }
});

test("counts normalized physical lines", () => {
  assert.equal(countPhysicalLines("one\r\ntwo\r\n"), 2);
  assert.equal(countPhysicalLines(""), 0);
});

test("fails a module that grows beyond its reviewed ceiling", () => {
  const [result] = evaluateFrontendModuleBudgets(
    [{ path: "large.tsx", baselineLines: 2, maximumLines: 2, maximumFunctionComplexity: 10 }],
    () => "one\ntwo\nthree\n",
  );
  assert.equal(result.actualLines, 3);
  assert.equal(result.withinBudget, false);
});

test("measures nested functions independently and fails complexity growth", () => {
  const source = `
    function parent(one, two) {
      if (one && two) return true;
      const child = (three) => three ? 1 : 0;
      return child(one);
    }
  `;
  assert.equal(maxFunctionCyclomaticComplexity(source, "sample.ts"), 3);
  const [result] = evaluateFrontendModuleBudgets(
    [{ path: "complex.ts", baselineLines: 7, maximumLines: 20, maximumFunctionComplexity: 2 }],
    () => source,
  );
  assert.equal(result.actualMaxFunctionComplexity, 3);
  assert.equal(result.withinBudget, false);
});
