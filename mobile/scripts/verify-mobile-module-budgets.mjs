import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const mobileRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/**
 * Baselines were measured after the F31 vault decomposition. Ceilings deliberately allow a small,
 * reviewable increment above that evidence while preventing the original 1,457-line vault and
 * other stateful infrastructure modules from silently regrowing.
 */
export const mobileModuleBudgets = Object.freeze([
  Object.freeze({
    path: 'src/features/content/data/content-repository.ts',
    baselineLines: 1_392,
    maximumLines: 1_425,
  }),
  Object.freeze({
    path: 'src/core/storage/database-schema.ts',
    baselineLines: 1_172,
    maximumLines: 1_200,
  }),
  Object.freeze({
    path: 'src/core/sync/snapshot-rebase-store.ts',
    baselineLines: 1_055,
    maximumLines: 1_085,
  }),
  Object.freeze({
    path: 'src/core/storage/vault.ts',
    baselineLines: 981,
    maximumLines: 1_050,
  }),
  Object.freeze({
    path: 'src/core/api/client.ts',
    baselineLines: 618,
    maximumLines: 675,
  }),
  Object.freeze({
    path: 'src/core/sync/sync-service.ts',
    baselineLines: 968,
    maximumLines: 1_000,
  }),
  Object.freeze({
    path: 'src/core/auth/session-service.ts',
    baselineLines: 891,
    maximumLines: 925,
  }),
  Object.freeze({
    path: 'src/features/coordinator/data/coordinator-repository.ts',
    baselineLines: 785,
    maximumLines: 825,
  }),
  Object.freeze({
    path: 'src/core/storage/secure-store.ts',
    baselineLines: 782,
    maximumLines: 825,
  }),
  Object.freeze({
    path: 'src/core/storage/database.ts',
    baselineLines: 720,
    maximumLines: 750,
  }),
  Object.freeze({
    path: 'src/core/storage/database-operation-coordinator.ts',
    baselineLines: 105,
    maximumLines: 130,
  }),
  Object.freeze({
    path: 'src/features/coordinator/data/attendance-queue.ts',
    baselineLines: 698,
    maximumLines: 725,
  }),
  Object.freeze({
    path: 'src/core/sync/snapshot-rebase.ts',
    baselineLines: 665,
    maximumLines: 700,
  }),
  Object.freeze({
    path: 'src/app/(coordinator)/(tabs)/scan.tsx',
    baselineLines: 575,
    maximumLines: 600,
  }),
  Object.freeze({
    path: 'src/features/coordinator/data/attendance-sessions.ts',
    baselineLines: 565,
    maximumLines: 600,
  }),
  Object.freeze({
    path: 'src/core/observability/mobile-observability.ts',
    baselineLines: 501,
    maximumLines: 550,
  }),
  Object.freeze({
    path: 'src/core/storage/vault-native-transfer.ts',
    baselineLines: 216,
    maximumLines: 250,
  }),
  Object.freeze({
    path: 'src/core/storage/vault-crypto.ts',
    baselineLines: 186,
    maximumLines: 225,
  }),
  Object.freeze({
    path: 'src/core/storage/vault-storage-quota.ts',
    baselineLines: 173,
    maximumLines: 200,
  }),
]);

export function countPhysicalLines(source) {
  const normalized = source.replace(/\r\n?/g, '\n');
  if (normalized.length === 0) return 0;
  const lines = normalized.split('\n');
  return lines.at(-1) === '' ? lines.length - 1 : lines.length;
}

export function evaluateMobileModuleBudgets(
  budgets = mobileModuleBudgets,
  readSource = (relativePath) => readFileSync(resolve(mobileRoot, relativePath), 'utf8'),
) {
  return budgets.map((budget) => {
    const actualLines = countPhysicalLines(readSource(budget.path));
    return Object.freeze({
      ...budget,
      actualLines,
      withinBudget: actualLines <= budget.maximumLines,
    });
  });
}

function run() {
  const results = evaluateMobileModuleBudgets();
  const failures = results.filter((result) => !result.withinBudget);
  if (failures.length > 0) {
    for (const failure of failures) {
      console.error(
        `${failure.path}: ${failure.actualLines} lines exceeds ${failure.maximumLines} `
        + `(F31 baseline ${failure.baselineLines}). Extract a cohesive module or update the `
        + 'budget with reviewed evidence.',
      );
    }
    process.exitCode = 1;
    return;
  }
  console.log(
    `Mobile module budgets passed (${results.length} high-risk production modules checked).`,
  );
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) run();
