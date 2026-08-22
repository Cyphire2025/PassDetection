import assert from "node:assert/strict";
import test from "node:test";
import {
  countPhysicalLines,
  evaluateFrontendModuleBudgets,
  maxFunctionCyclomaticComplexity,
} from "./verify-frontend-module-budgets.mjs";

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
