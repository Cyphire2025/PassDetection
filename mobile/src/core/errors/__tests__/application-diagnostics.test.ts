import {
  clearApplicationDiagnosticsForTests,
  recentApplicationDiagnostics,
  recordApplicationDiagnostic,
} from '../application-diagnostics';

beforeEach(clearApplicationDiagnosticsForTests);

test('accepts only fixed diagnostic fields and bounds recovery attempts', () => {
  recordApplicationDiagnostic('APP_RENDER_FAILED', 99);
  expect(recentApplicationDiagnostics()).toEqual([{ code: 'APP_RENDER_FAILED', attempt: 3 }]);
});

test('keeps a bounded process-local trail', () => {
  for (let index = 0; index < 25; index += 1) {
    recordApplicationDiagnostic('APP_RECOVERY_REQUESTED', index);
  }
  expect(recentApplicationDiagnostics()).toHaveLength(20);
});
