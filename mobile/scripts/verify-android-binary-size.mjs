import { statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { extname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const {
  ANDROID_RELEASE_BINARY_SIZE_BUDGETS,
  formatMebibytes,
} = require('./android-release-policy.js');

/** Internal release budgets. They are deliberately below the currently
 * observed 172.38 MiB four-ABI APK, which is a release blocker rather than a
 * baseline to grandfather. Play-delivered ABI/resource splits are still
 * measured separately during distribution validation. */
export { ANDROID_RELEASE_BINARY_SIZE_BUDGETS };

export const OBSERVED_UNACCEPTABLE_UNIVERSAL_APK_BYTES = 180_750_134;

export { formatMebibytes };

export function evaluateAndroidBinarySizes(
  artifacts,
  budgets = ANDROID_RELEASE_BINARY_SIZE_BUDGETS,
) {
  const failures = [];
  for (const artifact of artifacts) {
    const maximumBytes = budgets[artifact.type];
    if (!Number.isSafeInteger(artifact.bytes) || artifact.bytes <= 0) {
      failures.push(`${artifact.type.toUpperCase()} size is invalid.`);
      continue;
    }
    if (!Number.isSafeInteger(maximumBytes) || maximumBytes <= 0) {
      failures.push(`${artifact.type.toUpperCase()} budget is invalid.`);
      continue;
    }
    if (artifact.bytes > maximumBytes) {
      failures.push(
        `${artifact.type.toUpperCase()} ${formatMebibytes(artifact.bytes)} exceeds `
        + `${formatMebibytes(maximumBytes)} (${artifact.bytes - maximumBytes} bytes over).`,
      );
    }
  }
  return failures;
}

function artifact(path, type) {
  const absolutePath = resolve(path);
  if (extname(absolutePath).toLowerCase() !== `.${type}`) {
    throw new Error(`Expected a .${type} release artifact.`);
  }
  const metadata = statSync(absolutePath);
  if (!metadata.isFile()) throw new Error(`The ${type.toUpperCase()} artifact is not a file.`);
  return Object.freeze({ type, bytes: metadata.size, path: absolutePath });
}

function run() {
  const [apkPath, aabPath] = process.argv.slice(2);
  if (!apkPath || !aabPath) {
    throw new Error('Usage: verify-android-binary-size <release.apk> <release.aab>');
  }
  const artifacts = [artifact(apkPath, 'apk'), artifact(aabPath, 'aab')];
  const failures = evaluateAndroidBinarySizes(artifacts);
  if (failures.length > 0) {
    throw new Error(`Android release binary size budget failed:\n- ${failures.join('\n- ')}`);
  }
  process.stdout.write(
    `Android release size budgets passed: APK ${formatMebibytes(artifacts[0].bytes)}, `
    + `AAB ${formatMebibytes(artifacts[1].bytes)}.\n`,
  );
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : null;
if (invokedPath === import.meta.url) {
  try {
    run();
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}
