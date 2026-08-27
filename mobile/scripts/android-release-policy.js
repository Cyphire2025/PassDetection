'use strict';

const MEBIBYTE = 1024 * 1024;

const ANDROID_RELEASE_BINARY_SIZE_BUDGETS = Object.freeze({
  apk: 120 * MEBIBYTE,
  aab: 150 * MEBIBYTE,
});

const ANDROID_ARM64_APK_ABIS = Object.freeze(['arm64-v8a']);
const ANDROID_X86_64_APK_ABIS = Object.freeze(['x86_64']);
const ANDROID_PLAY_BUNDLE_ABIS = Object.freeze([
  'arm64-v8a',
  'armeabi-v7a',
  'x86',
  'x86_64',
]);

function formatMebibytes(bytes) {
  return `${(bytes / MEBIBYTE).toFixed(2)} MiB`;
}

function assertAndroidArtifactSize(type, bytes) {
  const maximumBytes = ANDROID_RELEASE_BINARY_SIZE_BUDGETS[type];
  if (!Number.isSafeInteger(bytes) || bytes <= 0) {
    throw new Error(`${String(type).toUpperCase()} size is invalid.`);
  }
  if (!maximumBytes) {
    throw new Error('Android release artifact type is invalid.');
  }
  if (bytes > maximumBytes) {
    throw new Error(
      `${type.toUpperCase()} ${formatMebibytes(bytes)} exceeds `
      + `${formatMebibytes(maximumBytes)} (${bytes - maximumBytes} bytes over).`,
    );
  }
}

function normalizeAndroidAbis(values, source) {
  if (!Array.isArray(values) || values.length === 0) {
    throw new Error(`${source} does not declare any native ABIs.`);
  }
  const normalized = values.map((value) => String(value).trim()).filter(Boolean).sort();
  if (normalized.length === 0 || normalized.length !== new Set(normalized).size) {
    throw new Error(`${source} native ABI metadata is invalid.`);
  }
  return normalized;
}

function assertExactAndroidAbis(actual, expected, source) {
  const normalizedActual = normalizeAndroidAbis(actual, source);
  const normalizedExpected = [...expected].sort();
  if (
    normalizedActual.length !== normalizedExpected.length
    || normalizedActual.some((abi, index) => abi !== normalizedExpected[index])
  ) {
    throw new Error(
      `${source} must contain exactly ${normalizedExpected.join(', ')} native ABI(s).`,
    );
  }
  return Object.freeze(normalizedActual);
}

function canonicalAndroidArtifactName({ type, buildId, gitCommitHash, nativeAbis }) {
  if (!['apk', 'aab'].includes(type)) {
    throw new Error('Android release artifact type is invalid.');
  }
  const lane = type === 'apk'
    ? `${nativeAbis?.[0] || 'unknown'}-sideload`
    : 'play-bundle';
  return `global-connect-travels-android-${lane}-${gitCommitHash.slice(0, 12).toLowerCase()}-${buildId.toLowerCase()}.${type}`;
}

module.exports = {
  ANDROID_ARM64_APK_ABIS,
  ANDROID_PLAY_BUNDLE_ABIS,
  ANDROID_RELEASE_BINARY_SIZE_BUDGETS,
  ANDROID_X86_64_APK_ABIS,
  assertAndroidArtifactSize,
  assertExactAndroidAbis,
  canonicalAndroidArtifactName,
  formatMebibytes,
};
