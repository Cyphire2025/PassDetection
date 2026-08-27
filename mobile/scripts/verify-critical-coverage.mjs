import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const mobileRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

export const criticalCoverageThresholds = Object.freeze({
  'src/core/api/client.ts': Object.freeze({ statements: 64, branches: 54, functions: 80, lines: 67 }),
  'src/core/api/native-file-download.ts': Object.freeze({ statements: 77, branches: 68, functions: 100, lines: 80 }),
  'src/core/auth/offline-authorization.ts': Object.freeze({ statements: 79, branches: 73, functions: 85, lines: 86 }),
  'src/core/auth/session-service.ts': Object.freeze({ statements: 63, branches: 52, functions: 74, lines: 68 }),
  'src/core/realtime/realtime-client.ts': Object.freeze({ statements: 83, branches: 72, functions: 72, lines: 88 }),
  'src/core/security/app-integrity.ts': Object.freeze({ statements: 81, branches: 68, functions: 84, lines: 93 }),
  'src/core/storage/vault-policy.ts': Object.freeze({ statements: 93, branches: 91, functions: 100, lines: 97 }),
  'src/core/sync/sync-context.ts': Object.freeze({ statements: 94, branches: 95, functions: 100, lines: 100 }),
  // The durable My Photos media plane is gated separately from the global
  // average. Planning and record mapping were extracted from the two large
  // state machines so their higher floors cannot be hidden by file movement.
  'src/features/my-photos/data/my-photos-repository.ts': Object.freeze({ statements: 28, branches: 16, functions: 46, lines: 27 }),
  'src/features/my-photos/downloads/download-manager.ts': Object.freeze({ statements: 28, branches: 23, functions: 38, lines: 31 }),
  'src/features/my-photos/downloads/download-repository.ts': Object.freeze({ statements: 30, branches: 27, functions: 31, lines: 33 }),
  'src/features/my-photos/downloads/photo-download-plan.ts': Object.freeze({ statements: 73, branches: 65, functions: 54, lines: 85 }),
  'src/features/my-photos/downloads/photo-download-record.ts': Object.freeze({ statements: 100, branches: 100, functions: 100, lines: 100 }),
});

function portablePath(value) {
  return value.replace(/\\/g, '/');
}

export function evaluateCriticalCoverage(summary, thresholds = criticalCoverageThresholds) {
  const entries = Object.entries(summary).map(([file, coverage]) => [portablePath(file), coverage]);
  const failures = [];
  for (const [relativePath, required] of Object.entries(thresholds)) {
    const entry = entries.find(([file]) => file.endsWith(`/${relativePath}`));
    if (!entry) {
      failures.push(`${relativePath}: missing from coverage summary`);
      continue;
    }
    const coverage = entry[1];
    for (const [metric, minimum] of Object.entries(required)) {
      const actual = coverage?.[metric]?.pct;
      if (typeof actual !== 'number' || !Number.isFinite(actual) || actual < minimum) {
        failures.push(`${relativePath}: ${metric} ${String(actual)}% is below ${minimum}%`);
      }
    }
  }
  return failures;
}

function run() {
  const summaryPath = resolve(mobileRoot, 'coverage', 'coverage-summary.json');
  const summary = JSON.parse(readFileSync(summaryPath, 'utf8'));
  const failures = evaluateCriticalCoverage(summary);
  if (failures.length > 0) {
    throw new Error(`Critical mobile coverage failed:\n- ${failures.join('\n- ')}`);
  }
  console.log(
    `Critical mobile coverage passed (${Object.keys(criticalCoverageThresholds).length} modules checked).`,
  );
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) run();
