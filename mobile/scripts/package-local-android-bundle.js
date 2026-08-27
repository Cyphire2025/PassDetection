/* global __dirname */
'use strict';

const { createHash, randomUUID } = require('node:crypto');
const {
  constants: fsConstants,
  copyFileSync,
  createReadStream,
  existsSync,
  statSync,
  unlinkSync,
  writeFileSync,
} = require('node:fs');
const { basename, join, resolve } = require('node:path');

const { CANONICAL_ANDROID_PACKAGE, parseApprovedFingerprints } = require('./verify-android-artifact');
const { inspectAndroidBundle } = require('./verify-android-bundle');
const { loadAndroidSourceVersion } = require('./android-release-source-version');
const { sourceManifest, sourceState } = require('./package-local-android-sideload');
const {
  nativeAndroidSourceManifest,
  validateNativeAndroidSourceSnapshot,
} = require('./android-native-source-manifest');
const {
  androidBuildConfigFingerprint,
  assertProductionAndroidReleaseEvidenceEnvironment,
  validateAndroidBuildConfigFingerprint,
} = require('./android-build-config-fingerprint');
const { loadReviewedGradleWrapper } = require('./android-release-toolchain');

function normalizedBuildTimestamp(value) {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) {
    throw new Error('Local Android build timestamp must be a valid ISO-8601 instant.');
  }
  return parsed.toISOString();
}

function assertArtifactBuiltAfter(artifact, buildTimestamp) {
  if (!Number.isFinite(artifact?.mtimeMs) || artifact.mtimeMs < Date.parse(buildTimestamp)) {
    throw new Error('The Android App Bundle predates the declared local build start.');
  }
}

function sha256File(filePath) {
  return new Promise((resolveHash, reject) => {
    const digest = createHash('sha256');
    const stream = createReadStream(filePath);
    stream.on('error', reject);
    stream.on('data', (chunk) => digest.update(chunk));
    stream.on('end', () => resolveHash(digest.digest('hex').toUpperCase()));
  });
}

function removeIfPresent(path) {
  if (path && existsSync(path)) unlinkSync(path);
}

function assertSameBundle(actual, expected) {
  if (
    actual.artifact_bytes !== expected.artifact_bytes
    || actual.artifact_sha256 !== expected.artifact_sha256
    || actual.signing_certificate_sha256 !== expected.signing_certificate_sha256
    || JSON.stringify(actual.native_abis) !== JSON.stringify(expected.native_abis)
    || JSON.stringify(actual.module_native_abis) !== JSON.stringify(expected.module_native_abis)
    || JSON.stringify(actual.manifest_metadata ?? null)
      !== JSON.stringify(expected.manifest_metadata ?? null)
    || JSON.stringify(actual.manifest_tool ?? null) !== JSON.stringify(expected.manifest_tool ?? null)
  ) {
    throw new Error('The Android App Bundle changed during local canonical packaging.');
  }
}

function canonicalLocalBundleName({ buildTimestamp, gitHead, snapshotHash, version }) {
  const timestamp = new Date(buildTimestamp).toISOString().replace(/[-:.]/g, '');
  const safeVersion = version.versionName.replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 80);
  return [
    'global-connect-travels',
    `v${safeVersion}`,
    `vc${String(version.versionCode)}`,
    'local-signed-play-bundle',
    gitHead.slice(0, 12),
    `src${snapshotHash.slice(0, 12).toLowerCase()}`,
    timestamp,
  ].join('-') + '.aab';
}

async function materializeLocalAndroidBundle(options, dependencies = {}) {
  const sourceArtifactPath = resolve(options.artifactPath || '');
  const outputDirectory = resolve(options.outputDirectory || '');
  if (!sourceArtifactPath.toLowerCase().endsWith('.aab')) {
    throw new Error('Local Android bundle packaging requires an AAB source.');
  }
  const outputMetadata = statSync(outputDirectory);
  if (!outputMetadata.isDirectory()) {
    throw new Error('The local App Bundle output path must be an existing directory.');
  }
  const buildTimestamp = normalizedBuildTimestamp(options.buildTimestamp);
  const sourceMetadata = statSync(sourceArtifactPath);
  if (!sourceMetadata.isFile() || sourceMetadata.size <= 0) {
    throw new Error('The local Android App Bundle is empty or unavailable.');
  }
  assertArtifactBuiltAfter(sourceMetadata, buildTimestamp);
  const approvedFingerprints = options.approvedFingerprints instanceof Set
    ? options.approvedFingerprints
    : parseApprovedFingerprints(
      options.approvedFingerprints
        ?? process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    );
  const expectedVersion = options.expectedVersion || loadAndroidSourceVersion();
  const mobileRoot = resolve(options.mobileRoot || join(__dirname, '..'));
  const gradleWrapper = options.gradleWrapper
    || (dependencies.loadReviewedGradleWrapper || loadReviewedGradleWrapper)(mobileRoot);
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
  const inspect = dependencies.inspectAndroidBundle || inspectAndroidBundle;
  const inspectionOptions = {
    approvedFingerprints,
    bundletoolPath: options.bundletoolPath,
    requireBinaryManifest: false,
  };
  const sourceDetails = await inspect(
    { ...inspectionOptions, artifactPath: sourceArtifactPath },
    dependencies,
  );

  const temporaryArtifactPath = join(
    outputDirectory,
    `.local-bundle-partial-${randomUUID()}.aab`,
  );
  let canonicalArtifactPath;
  let receiptPath;
  let canonicalCreated = false;
  try {
    copyFileSync(sourceArtifactPath, temporaryArtifactPath, fsConstants.COPYFILE_EXCL);
    const temporaryDetails = await inspect(
      { ...inspectionOptions, artifactPath: temporaryArtifactPath },
      dependencies,
    );
    assertSameBundle(temporaryDetails, sourceDetails);
    const currentSourceHash = await (dependencies.sha256File || sha256File)(sourceArtifactPath);
    if (
      currentSourceHash !== temporaryDetails.artifact_sha256
      || sourceMetadata.size !== temporaryDetails.artifact_bytes
    ) {
      throw new Error('The Gradle App Bundle changed while its canonical copy was being created.');
    }

    const repoRoot = resolve(options.repoRoot || join(__dirname, '..', '..'));
    const source = dependencies.sourceState || sourceState(repoRoot, dependencies);
    const snapshot = dependencies.sourceManifest || sourceManifest(repoRoot, dependencies);
    const canonicalArtifactFile = canonicalLocalBundleName({
      buildTimestamp,
      gitHead: source.git_head,
      snapshotHash: snapshot.sha256,
      version: expectedVersion,
    });
    canonicalArtifactPath = join(outputDirectory, canonicalArtifactFile);
    receiptPath = `${canonicalArtifactPath}.receipt.json`;
    if (existsSync(canonicalArtifactPath) || existsSync(receiptPath)) {
      throw new Error('The canonical local App Bundle artifact or receipt already exists.');
    }
    copyFileSync(temporaryArtifactPath, canonicalArtifactPath, fsConstants.COPYFILE_EXCL);
    canonicalCreated = true;
    unlinkSync(temporaryArtifactPath);
    const finalDetails = await inspect(
      { ...inspectionOptions, artifactPath: canonicalArtifactPath },
      dependencies,
    );
    assertSameBundle(finalDetails, temporaryDetails);
    const binaryMetadata = finalDetails.manifest_metadata || null;
    if (
      binaryMetadata
      && (
        binaryMetadata.packageName !== CANONICAL_ANDROID_PACKAGE
        || binaryMetadata.versionName !== expectedVersion.versionName
        || binaryMetadata.versionCode !== expectedVersion.versionCode
      )
    ) {
      throw new Error('Local Android App Bundle manifest does not match checked-out source expectations.');
    }
    const finalNativeSnapshot = validateNativeAndroidSourceSnapshot(loadNativeSnapshot());
    if (finalNativeSnapshot.sha256 !== initialNativeSnapshot.sha256) {
      throw new Error('Generated Android native sources changed during local App Bundle packaging.');
    }
    const finalBuildConfigFingerprint = validateAndroidBuildConfigFingerprint(
      loadBuildConfigFingerprint(),
    );
    if (finalBuildConfigFingerprint.sha256 !== initialBuildConfigFingerprint.sha256) {
      throw new Error('Android build configuration changed during local App Bundle packaging.');
    }
    const generatedAt = (dependencies.now ? dependencies.now() : new Date()).toISOString();
    const receipt = Object.freeze({
      schema_version: 2,
      evidence_level: 'local_signed_play_bundle',
      release_eligible: false,
      provenance_scope: 'post_build_local_source_association_not_source_to_build_attestation',
      artifact_type: 'aab',
      source_artifact_file: basename(sourceArtifactPath),
      canonical_artifact_file: canonicalArtifactFile,
      artifact_bytes: finalDetails.artifact_bytes,
      artifact_sha256: finalDetails.artifact_sha256,
      expected_package_name: CANONICAL_ANDROID_PACKAGE,
      ...(binaryMetadata ? { package_name: binaryMetadata.packageName } : {}),
      package_evidence: binaryMetadata
        ? `bundletool_${finalDetails.manifest_tool.version}_binary_manifest`
        : 'expected_from_checked_out_source_not_archive_manifest; pinned_bundletool_unavailable',
      expected_source_version_name: expectedVersion.versionName,
      expected_source_version_code: expectedVersion.versionCode,
      ...(binaryMetadata ? {
        version_name: binaryMetadata.versionName,
        version_code: binaryMetadata.versionCode,
        manifest_tool: finalDetails.manifest_tool,
      } : {}),
      version_evidence: binaryMetadata
        ? `version_name_and_code=bundletool_${finalDetails.manifest_tool.version}_binary_manifest+checked_out_source_expectation`
        : 'checked_out_source_expectation_not_archive_derived; pinned_bundletool_unavailable',
      native_abis: finalDetails.native_abis,
      module_native_abis: finalDetails.module_native_abis,
      native_android_snapshot: finalNativeSnapshot,
      build_config_fingerprint: finalBuildConfigFingerprint,
      signing_certificate_sha256: finalDetails.signing_certificate_sha256,
      signing_assertion: 'all_entries_cryptographically_verified+single_signer_block+approved_distribution_fingerprint',
      build_timestamp_utc: buildTimestamp,
      receipt_generated_at_utc: generatedAt,
      source_dirty: source.repository_dirty,
      mobile_source_dirty: source.mobile_source_dirty,
      git_head: source.git_head,
      source_snapshot_timing: 'captured_after_artifact_build',
      mobile_source_snapshot: snapshot,
      tool_versions: Object.freeze({
        node: process.version,
        gradle_wrapper: gradleWrapper.distributionUrl.split('/').at(-1),
        gradle_distribution_sha256: gradleWrapper.distributionSha256,
      }),
    });
    writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o600,
    });
    return Object.freeze({ canonicalArtifactPath, receipt, receiptPath });
  } catch (error) {
    removeIfPresent(temporaryArtifactPath);
    if (canonicalCreated) removeIfPresent(canonicalArtifactPath);
    throw error;
  }
}

function parseCliArguments(args) {
  if (!Array.isArray(args) || args.length !== 3 || args.some((argument) => !argument)) {
    throw new Error(
      'Usage: package-local-android-bundle <aab> <existing-output-directory> <build-timestamp-utc>',
    );
  }
  const [artifactPath, outputDirectory, buildTimestamp] = args;
  return Object.freeze({ artifactPath, buildTimestamp, outputDirectory });
}

async function main() {
  assertProductionAndroidReleaseEvidenceEnvironment();
  const options = parseCliArguments(process.argv.slice(2));
  const result = await materializeLocalAndroidBundle({
    ...options,
    approvedFingerprints: parseApprovedFingerprints(
      process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    ),
    expectedVersion: loadAndroidSourceVersion(),
  });
  process.stdout.write(
    `Created local-only signed App Bundle evidence ${basename(result.canonicalArtifactPath)} with adjacent receipt ${basename(result.receiptPath)}.\n`,
  );
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

module.exports = {
  assertSameBundle,
  canonicalLocalBundleName,
  materializeLocalAndroidBundle,
  parseCliArguments,
};
