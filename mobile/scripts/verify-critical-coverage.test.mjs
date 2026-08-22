import assert from 'node:assert/strict';
import test from 'node:test';

import { evaluateCriticalCoverage } from './verify-critical-coverage.mjs';

const thresholds = {
  'src/core/api/client.ts': { statements: 80, branches: 70, functions: 90, lines: 80 },
};

test('accepts a portable absolute path that meets every critical floor', () => {
  const failures = evaluateCriticalCoverage({
    'C:\\workspace\\mobile\\src\\core\\api\\client.ts': {
      statements: { pct: 80 },
      branches: { pct: 70 },
      functions: { pct: 90 },
      lines: { pct: 80 },
    },
  }, thresholds);
  assert.deepEqual(failures, []);
});

test('reports missing modules and individual metric regressions', () => {
  assert.deepEqual(evaluateCriticalCoverage({}, thresholds), [
    'src/core/api/client.ts: missing from coverage summary',
  ]);
  const failures = evaluateCriticalCoverage({
    '/workspace/mobile/src/core/api/client.ts': {
      statements: { pct: 79.99 },
      branches: { pct: 70 },
      functions: { pct: 90 },
      lines: { pct: 80 },
    },
  }, thresholds);
  assert.deepEqual(failures, [
    'src/core/api/client.ts: statements 79.99% is below 80%',
  ]);
});
