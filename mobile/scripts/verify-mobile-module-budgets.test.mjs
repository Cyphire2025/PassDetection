import assert from 'node:assert/strict';
import test from 'node:test';

import {
  countPhysicalLines,
  evaluateMobileModuleBudgets,
  mobileModuleBudgets,
} from './verify-mobile-module-budgets.mjs';

test('counts LF and CRLF source files consistently', () => {
  assert.equal(countPhysicalLines('first\nsecond\n'), 2);
  assert.equal(countPhysicalLines('first\r\nsecond\r\n'), 2);
  assert.equal(countPhysicalLines(''), 0);
});

test('current high-risk production modules remain within reviewed budgets', () => {
  const results = evaluateMobileModuleBudgets();
  assert.equal(results.length, mobileModuleBudgets.length);
  assert.deepEqual(
    results.filter((result) => !result.withinBudget),
    [],
  );
});

test('reports a module that crosses its reviewed ceiling', () => {
  const [result] = evaluateMobileModuleBudgets(
    [{ path: 'fixture.ts', baselineLines: 2, maximumLines: 3 }],
    () => 'one\ntwo\nthree\nfour\n',
  );
  assert.equal(result?.actualLines, 4);
  assert.equal(result?.withinBudget, false);
});
