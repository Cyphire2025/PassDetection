'use strict';
/* global __dirname */

const { createHash, randomUUID } = require('node:crypto');
const {
  constants: fsConstants,
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  statSync,
  unlinkSync,
  writeFileSync,
} = require('node:fs');
const {
  basename,
  dirname,
  join,
  resolve,
} = require('node:path');

const {
  CANONICAL_ANDROID_PACKAGE,
  expectedApkAbis,
  parseApkNativeAbis,
  parseApkSignerOutput,
  parseApprovedFingerprints,
  parsePackageMetadata,
  resolveAndroidBuildTools,
  runTool,
  sha256File,
} = require('./verify-android-artifact');
const { assertAndroidArtifactSize } = require('./android-release-policy');
const {
  assertAndroidVersionMetadata,
  loadAndroidSourceVersion,
} = require('./android-release-source-version');
const {
  nativeAndroidSourceManifest,
  validateNativeAndroidSourceSnapshot,
} = require('./android-native-source-manifest');
const {
  androidBuildConfigFingerprint,
  assertProductionAndroidReleaseEvidenceEnvironment,
  validateAndroidBuildConfigFingerprint,
} = require('./android-build-config-fingerprint');

const STAGING_SCHEMA_VERSION = 2;
const LANE_STAGED_APK_FILENAMES = Object.freeze({
  'arm64-v8a': 'app-release-arm64-v8a.apk',
  x86_64: 'app-release-x86_64.apk',
});

function laneStagedArtifactPaths(expectedAbi, mobileRoot = resolve(__dirname, '..')) {
  expectedApkAbis(expectedAbi);
  const root = resolve(mobileRoot);
  const filename = LANE_STAGED_APK_FILENAMES[expectedAbi];
  return Object.freeze({
    durable: join(root, 'outputs', 'android-staging', filename),
    legacy: join(
      root,
      'android',
      'app',
      'build',
      'outputs',
      'apk',
      'release',
      'staged',
      filename,
    ),
  });
}

function sameResolvedPath(left, right) {
  const normalizedLeft = resolve(left);
  const normalizedRight = resolve(right);
  return process.platform === 'win32'
    ? normalizedLeft.toLowerCase() === normalizedRight.toLowerCase()
    : normalizedLeft === normalizedRight;
}

function resolveLaneStagedArtifactPath(requestedPath, expectedAbi, options = {}) {
  const requested = resolve(requestedPath || '');
  const paths = laneStagedArtifactPaths(expectedAbi, options.mobileRoot);
  if (
    !sameResolvedPath(requested, paths.legacy)
    && !sameResolvedPath(requested, paths.durable)
  ) return requested;
  if (options.action === 'stage') return paths.durable;
  if (options.action !== 'verify') {
    throw new Error('Android lane staging path resolution action is invalid.');
  }
  const pathExists = options.exists || existsSync;
  if (pathExists(paths.durable) || !pathExists(paths.legacy)) return paths.durable;
  return paths.legacy;
}

function stagingManifestPath(artifactPath) {
  return `${resolve(artifactPath)}.stage.json`;
}

function removeIfPresent(path) {
  if (path && existsSync(path)) unlinkSync(path);
}

function approvedFingerprintSet(value) {
  return value instanceof Set ? value : parseApprovedFingerprints(value);
}

function stagingPolicy(options = {}) {
  return Object.freeze({
    approvedFingerprints: approvedFingerprintSet(
      options.approvedFingerprints
        ?? process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    ),
    expectedVersion: options.expectedVersion || loadAndroidSourceVersion(),
  });
}

async function inspectStagedApk(artifactPath, expectedAbi, policyOptions = {}, dependencies = {}) {
  const absolutePath = resolve(artifactPath || '');
  if (!absolutePath.toLowerCase().endsWith('.apk')) {
    throw new Error('The staged Android artifact must be an APK.');
  }
  const artifact = statSync(absolutePath);
  if (!artifact.isFile() || artifact.size <= 0) {
    throw new Error('The staged Android APK is empty or unavailable.');
  }
  assertAndroidArtifactSize('apk', artifact.size);
  const expectedAbis = expectedApkAbis(expectedAbi);
  const tools = dependencies.tools || resolveAndroidBuildTools(dependencies.environment);
  const execute = dependencies.runTool || runTool;
  const signer = parseApkSignerOutput(
    execute(tools.apksigner, ['verify', '--verbose', '--print-certs', absolutePath]),
  );
  const policy = stagingPolicy(policyOptions);
  if (!policy.approvedFingerprints.has(signer)) {
    throw new Error('The staged Android APK signer is not in the approved distribution fingerprint set.');
  }
  const packageOutput = execute(tools.aapt2, ['dump', 'badging', absolutePath]);
  const packageMetadata = parsePackageMetadata(packageOutput);
  if (packageMetadata.packageName !== CANONICAL_ANDROID_PACKAGE) {
    throw new Error('The staged Android APK does not use the canonical application package.');
  }
  assertAndroidVersionMetadata(packageMetadata, policy.expectedVersion, 'Staged Android APK');
  const nativeAbis = parseApkNativeAbis(packageOutput, expectedAbis);
  return Object.freeze({
    artifact_bytes: artifact.size,
    artifact_sha256: await (dependencies.sha256File || sha256File)(absolutePath),
    native_abis: nativeAbis,
    package_name: packageMetadata.packageName,
    signing_certificate_sha256: signer,
    version_code: packageMetadata.versionCode,
    version_name: packageMetadata.versionName,
  });
}

function assertSameStagedArtifact(actual, expected) {
  if (
    actual.artifact_bytes !== expected.artifact_bytes
    || actual.artifact_sha256 !== expected.artifact_sha256
    || actual.package_name !== expected.package_name
    || actual.version_name !== expected.version_name
    || actual.version_code !== expected.version_code
    || actual.signing_certificate_sha256 !== expected.signing_certificate_sha256
    || JSON.stringify(actual.native_abis) !== JSON.stringify(expected.native_abis)
  ) {
    throw new Error('The staged Android APK changed after its verified copy was created.');
  }
}

function parseStagingManifest(value) {
  let document;
  try {
    document = JSON.parse(value);
  } catch {
    throw new Error('The Android APK staging manifest is invalid.');
  }
  if (
    document?.schema_version !== STAGING_SCHEMA_VERSION
    || document?.evidence_level !== 'local_build_staging_only'
    || typeof document?.source_artifact_file !== 'string'
    || typeof document?.source_artifact_sha256 !== 'string'
    || !Number.isSafeInteger(document?.source_artifact_bytes)
    || typeof document?.temporary_artifact_sha256 !== 'string'
    || !Number.isSafeInteger(document?.temporary_artifact_bytes)
    || typeof document?.artifact_file !== 'string'
    || typeof document?.artifact_sha256 !== 'string'
    || !Number.isSafeInteger(document?.artifact_bytes)
    || typeof document?.package_name !== 'string'
    || typeof document?.version_name !== 'string'
    || !Number.isSafeInteger(document?.version_code)
    || document.version_code <= 0
    || typeof document?.target_abi !== 'string'
    || !Array.isArray(document?.native_abis)
    || typeof document?.signing_certificate_sha256 !== 'string'
    || typeof document?.native_android_snapshot?.sha256 !== 'string'
    || !Array.isArray(document?.native_android_snapshot?.manifest?.entries)
    || typeof document?.build_config_fingerprint?.sha256 !== 'string'
    || !Array.isArray(document?.build_config_fingerprint?.manifest?.entries)
  ) {
    throw new Error('The Android APK staging manifest is invalid.');
  }
  if (
    !/^[0-9A-F]{64}$/.test(document.source_artifact_sha256)
    || !/^[0-9A-F]{64}$/.test(document.temporary_artifact_sha256)
    || !/^[0-9A-F]{64}$/.test(document.artifact_sha256)
    || document.source_artifact_sha256 !== document.temporary_artifact_sha256
    || document.temporary_artifact_sha256 !== document.artifact_sha256
    || document.source_artifact_bytes !== document.temporary_artifact_bytes
    || document.temporary_artifact_bytes !== document.artifact_bytes
  ) {
    throw new Error('The Android APK staging manifest does not bind one source, temporary, and final artifact.');
  }
  validateNativeAndroidSourceSnapshot(document.native_android_snapshot);
  validateAndroidBuildConfigFingerprint(document.build_config_fingerprint);
  return document;
}

async function stageAndroidApk(options, dependencies = {}) {
  const sourceArtifactPath = resolve(options.sourceArtifactPath || '');
  const stagedArtifactPath = resolve(options.stagedArtifactPath || '');
  if (
    !sourceArtifactPath.toLowerCase().endsWith('.apk')
    || !stagedArtifactPath.toLowerCase().endsWith('.apk')
  ) {
    throw new Error('Android APK staging requires source and destination .apk paths.');
  }
  if (sourceArtifactPath.toLowerCase() === stagedArtifactPath.toLowerCase()) {
    throw new Error('Android APK staging source and destination must be different files.');
  }
  expectedApkAbis(options.expectedAbi);
  const policy = stagingPolicy(options);
  const mobileRoot = resolve(options.mobileRoot || resolve(__dirname, '..'));
  const loadNativeSnapshot = options.nativeSnapshot
    ? () => options.nativeSnapshot
    : () => (dependencies.nativeAndroidSourceManifest || nativeAndroidSourceManifest)(
      mobileRoot,
      dependencies,
    );
  const initialNativeSnapshot = validateNativeAndroidSourceSnapshot(loadNativeSnapshot());
  const loadBuildConfigFingerprint = options.buildConfigFingerprint
    ? () => options.buildConfigFingerprint
    : () => (dependencies.androidBuildConfigFingerprint || androidBuildConfigFingerprint)(
      mobileRoot,
      options.environment || dependencies.environment || process.env,
      dependencies,
    );
  const initialBuildConfigFingerprint = validateAndroidBuildConfigFingerprint(
    loadBuildConfigFingerprint(),
  );
  const sourceMetadata = statSync(sourceArtifactPath);
  if (!sourceMetadata.isFile() || sourceMetadata.size <= 0) {
    throw new Error('The Android APK staging source is empty or unavailable.');
  }
  assertAndroidArtifactSize('apk', sourceMetadata.size);
  const manifestPath = stagingManifestPath(stagedArtifactPath);
  if (existsSync(stagedArtifactPath) || existsSync(manifestPath)) {
    throw new Error('The lane-specific staged APK or staging manifest already exists.');
  }
  mkdirSync(dirname(stagedArtifactPath), { recursive: true });
  const temporaryPath = `${stagedArtifactPath}.partial-${randomUUID()}.apk`;
  let stagedCreated = false;
  let manifestCreated = false;
  try {
    const sourceDetails = await inspectStagedApk(
      sourceArtifactPath,
      options.expectedAbi,
      policy,
      dependencies,
    );
    copyFileSync(sourceArtifactPath, temporaryPath, fsConstants.COPYFILE_EXCL);
    const temporaryDetails = await inspectStagedApk(
      temporaryPath,
      options.expectedAbi,
      policy,
      dependencies,
    );
    const sourceHash = await (dependencies.sha256File || sha256File)(sourceArtifactPath);
    if (
      sourceMetadata.size !== temporaryDetails.artifact_bytes
      || sourceHash !== temporaryDetails.artifact_sha256
    ) {
      throw new Error('The Gradle APK changed while its lane-specific copy was being created.');
    }
    assertSameStagedArtifact(temporaryDetails, sourceDetails);
    copyFileSync(temporaryPath, stagedArtifactPath, fsConstants.COPYFILE_EXCL);
    stagedCreated = true;
    unlinkSync(temporaryPath);
    const finalDetails = await inspectStagedApk(
      stagedArtifactPath,
      options.expectedAbi,
      policy,
      dependencies,
    );
    assertSameStagedArtifact(finalDetails, temporaryDetails);
    const finalNativeSnapshot = validateNativeAndroidSourceSnapshot(loadNativeSnapshot());
    if (finalNativeSnapshot.sha256 !== initialNativeSnapshot.sha256) {
      throw new Error('Generated Android native sources changed during APK staging.');
    }
    const finalBuildConfigFingerprint = validateAndroidBuildConfigFingerprint(
      loadBuildConfigFingerprint(),
    );
    if (finalBuildConfigFingerprint.sha256 !== initialBuildConfigFingerprint.sha256) {
      throw new Error('Android build configuration changed during APK staging.');
    }
    const stagedAt = (dependencies.now ? dependencies.now() : new Date()).toISOString();
    const manifest = Object.freeze({
      schema_version: STAGING_SCHEMA_VERSION,
      evidence_level: 'local_build_staging_only',
      source_artifact_file: basename(sourceArtifactPath),
      source_artifact_bytes: sourceDetails.artifact_bytes,
      source_artifact_sha256: sourceDetails.artifact_sha256,
      temporary_artifact_bytes: temporaryDetails.artifact_bytes,
      temporary_artifact_sha256: temporaryDetails.artifact_sha256,
      artifact_file: basename(stagedArtifactPath),
      artifact_bytes: finalDetails.artifact_bytes,
      artifact_sha256: finalDetails.artifact_sha256,
      package_name: finalDetails.package_name,
      version_name: finalDetails.version_name,
      version_code: finalDetails.version_code,
      target_abi: options.expectedAbi,
      native_abis: finalDetails.native_abis,
      signing_certificate_sha256: finalDetails.signing_certificate_sha256,
      native_android_snapshot: finalNativeSnapshot,
      build_config_fingerprint: finalBuildConfigFingerprint,
      staged_at_utc: stagedAt,
    });
    writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o600,
    });
    manifestCreated = true;
    return Object.freeze({ manifest, manifestPath, stagedArtifactPath });
  } catch (error) {
    removeIfPresent(temporaryPath);
    if (stagedCreated) removeIfPresent(stagedArtifactPath);
    if (manifestCreated) removeIfPresent(manifestPath);
    throw error;
  }
}

async function verifyStagedAndroidApk(options, dependencies = {}) {
  const artifactPath = resolve(options.artifactPath || '');
  const manifestPath = stagingManifestPath(artifactPath);
  if (!existsSync(manifestPath)) {
    throw new Error('The lane-specific Android APK staging manifest is unavailable.');
  }
  const manifestBytes = readFileSync(manifestPath);
  const manifest = parseStagingManifest(manifestBytes.toString('utf8'));
  const nativeSnapshot = options.nativeSnapshot
    || nativeAndroidSourceManifest(resolve(__dirname, '..'));
  validateNativeAndroidSourceSnapshot(nativeSnapshot);
  const buildConfigFingerprint = options.buildConfigFingerprint
    || (dependencies.androidBuildConfigFingerprint || androidBuildConfigFingerprint)(
      resolve(__dirname, '..'),
      options.environment || dependencies.environment || process.env,
      dependencies,
    );
  validateAndroidBuildConfigFingerprint(buildConfigFingerprint);
  if (
    manifest.artifact_file !== basename(artifactPath)
    || manifest.target_abi !== options.expectedAbi
    || manifest.native_android_snapshot.sha256 !== nativeSnapshot.sha256
    || manifest.build_config_fingerprint.sha256 !== buildConfigFingerprint.sha256
  ) {
    throw new Error('The Android APK staging manifest does not match the requested lane.');
  }
  const actual = await inspectStagedApk(
    artifactPath,
    options.expectedAbi,
    stagingPolicy(options),
    dependencies,
  );
  assertSameStagedArtifact(actual, manifest);
  return Object.freeze({
    artifactPath,
    manifest,
    manifestPath,
    manifestSha256: createHash('sha256').update(manifestBytes).digest('hex').toUpperCase(),
    nativeSnapshot,
    buildConfigFingerprint,
  });
}

function parseCliArguments(args) {
  if (!Array.isArray(args) || !['stage', 'verify'].includes(args[0])) {
    throw new Error(
      'Usage: stage-android-apk stage <source.apk> <lane.apk> <arm64-v8a|x86_64> | verify <lane.apk> <arm64-v8a|x86_64>',
    );
  }
  if (args[0] === 'stage' && args.length === 4 && args.slice(1).every(Boolean)) {
    return Object.freeze({
      action: 'stage',
      sourceArtifactPath: args[1],
      stagedArtifactPath: args[2],
      expectedAbi: args[3],
    });
  }
  if (args[0] === 'verify' && args.length === 3 && args.slice(1).every(Boolean)) {
    return Object.freeze({
      action: 'verify',
      artifactPath: args[1],
      expectedAbi: args[2],
    });
  }
  throw new Error(
    'Usage: stage-android-apk stage <source.apk> <lane.apk> <arm64-v8a|x86_64> | verify <lane.apk> <arm64-v8a|x86_64>',
  );
}

async function main() {
  assertProductionAndroidReleaseEvidenceEnvironment();
  const options = parseCliArguments(process.argv.slice(2));
  const policy = {
    approvedFingerprints: parseApprovedFingerprints(
      process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    ),
    expectedVersion: loadAndroidSourceVersion(),
  };
  if (options.action === 'stage') {
    const result = await stageAndroidApk({
      ...options,
      ...policy,
      stagedArtifactPath: resolveLaneStagedArtifactPath(
        options.stagedArtifactPath,
        options.expectedAbi,
        { action: 'stage' },
      ),
    });
    process.stdout.write(
      `Staged ${basename(result.stagedArtifactPath)} with verified hash ${result.manifest.artifact_sha256}.\n`,
    );
    return;
  }
  const result = await verifyStagedAndroidApk({
    ...options,
    ...policy,
    artifactPath: resolveLaneStagedArtifactPath(
      options.artifactPath,
      options.expectedAbi,
      { action: 'verify' },
    ),
  });
  process.stdout.write(
    `Re-verified ${basename(result.artifactPath)} against its lane staging manifest.\n`,
  );
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

module.exports = {
  inspectStagedApk,
  laneStagedArtifactPaths,
  parseCliArguments,
  parseStagingManifest,
  resolveLaneStagedArtifactPath,
  stageAndroidApk,
  stagingManifestPath,
  verifyStagedAndroidApk,
};
