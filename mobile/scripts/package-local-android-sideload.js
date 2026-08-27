'use strict';

const { spawnSync } = require('node:child_process');
const { Buffer } = require('node:buffer');
const { createHash, randomUUID } = require('node:crypto');
const {
  constants: fsConstants,
  copyFileSync,
  existsSync,
  lstatSync,
  readFileSync,
  statSync,
  unlinkSync,
  writeFileSync,
} = require('node:fs');
const { basename, dirname, join, resolve } = require('node:path');

const {
  CANONICAL_ANDROID_PACKAGE,
  REVIEWED_ANDROID_BUILD_TOOLS_VERSION,
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
  resolveLaneStagedArtifactPath,
  verifyStagedAndroidApk,
} = require('./stage-android-apk');
const {
  assertProductionAndroidReleaseEvidenceEnvironment,
} = require('./android-build-config-fingerprint');
const { loadReviewedGradleWrapper } = require('./android-release-toolchain');

const GIT_COMMIT_PATTERN = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i;
const REVIEWED_AAPT2_VERSION_OUTPUT =
  'Android Asset Packaging Tool (aapt) 2.20-15087165';
const MOBILE_SOURCE_MANIFEST_EXCLUSIONS = Object.freeze([
  '.env',
  '.env.* (except .env.example)',
  '.expo/',
  'android/ (captured separately by reviewed native allowlist)',
  'coverage/',
  'dist/',
  'ios/',
  'node_modules/',
  'outputs/',
  'google-services.json',
  '*.jks',
  '*.keystore',
  '*.pem',
]);

function sha256Bytes(value) {
  return createHash('sha256').update(value).digest('hex').toUpperCase();
}

function runGit(repoRoot, args) {
  const result = spawnSync('git', ['-C', repoRoot, ...args], {
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
    shell: false,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Local source inspection failed with exit ${String(result.status)}.`);
  }
  return result.stdout || '';
}

function isExcludedMobileSourcePath(mobileRelativePath) {
  const normalized = mobileRelativePath.replaceAll('\\', '/');
  const lower = normalized.toLowerCase();
  if (lower === '.env.example') return false;
  if (lower === '.env' || lower.startsWith('.env.')) return true;
  if (['google-services.json'].includes(lower)) return true;
  if (/\.(?:jks|keystore|pem)$/i.test(normalized)) return true;
  return ['.expo/', 'android/', 'coverage/', 'dist/', 'ios/', 'node_modules/', 'outputs/']
    .some((prefix) => lower.startsWith(prefix));
}

function sourceManifest(repoRoot, dependencies = {}) {
  const executeGit = dependencies.runGit || runGit;
  const readBytes = dependencies.readFile || readFileSync;
  const inspectPath = dependencies.lstat || lstatSync;
  const listed = executeGit(
    repoRoot,
    ['ls-files', '-z', '--cached', '--others', '--exclude-standard', '--', 'mobile'],
  );
  const repositoryPaths = listed
    .split('\0')
    .filter(Boolean)
    .map((path) => path.replaceAll('\\', '/'))
    .filter((path) => path.startsWith('mobile/'))
    .sort();

  const entries = [];
  for (const repositoryPath of repositoryPaths) {
    const mobileRelativePath = repositoryPath.slice('mobile/'.length);
    if (isExcludedMobileSourcePath(mobileRelativePath)) continue;
    const absolutePath = resolve(repoRoot, repositoryPath);
    const metadata = inspectPath(absolutePath);
    if (!metadata.isFile()) {
      throw new Error('The mobile source snapshot contains an unsupported non-file entry.');
    }
    const bytes = readBytes(absolutePath);
    entries.push(Object.freeze({
      path: mobileRelativePath,
      bytes: bytes.length,
      sha256: sha256Bytes(bytes),
    }));
  }
  if (entries.length === 0) {
    throw new Error('The mobile source snapshot is empty.');
  }

  const manifest = Object.freeze({
    schema_version: 1,
    root: 'mobile',
    selection: 'git tracked plus non-ignored untracked files',
    exclusions: MOBILE_SOURCE_MANIFEST_EXCLUSIONS,
    entries,
  });
  const canonicalManifest = `${JSON.stringify(manifest)}\n`;
  return Object.freeze({
    file_count: entries.length,
    total_bytes: entries.reduce((total, entry) => total + entry.bytes, 0),
    sha256: sha256Bytes(Buffer.from(canonicalManifest, 'utf8')),
    manifest,
  });
}

function sourceState(repoRoot, dependencies = {}) {
  const executeGit = dependencies.runGit || runGit;
  const gitHead = executeGit(repoRoot, ['rev-parse', 'HEAD']).trim();
  if (!GIT_COMMIT_PATTERN.test(gitHead)) {
    throw new Error('Local source Git HEAD is invalid.');
  }
  const repositoryDirty = Boolean(executeGit(
    repoRoot,
    ['status', '--porcelain', '-z', '--untracked-files=all'],
  ));
  const mobileSourceDirty = Boolean(executeGit(
    repoRoot,
    ['status', '--porcelain', '-z', '--untracked-files=all', '--', 'mobile'],
  ));
  return Object.freeze({
    git_head: gitHead.toLowerCase(),
    repository_dirty: repositoryDirty,
    mobile_source_dirty: mobileSourceDirty,
  });
}

function boundedVersion(value, name) {
  const normalized = String(value || '').replace(/\s+/g, ' ').trim();
  if (!normalized || normalized.length > 256) {
    throw new Error(`${name} version could not be recorded safely.`);
  }
  return normalized;
}

function parseReviewedAapt2Version(value) {
  const normalized = boundedVersion(value, 'aapt2');
  if (normalized !== REVIEWED_AAPT2_VERSION_OUTPUT) {
    throw new Error(
      `aapt2 version does not match reviewed Android Build Tools ${REVIEWED_ANDROID_BUILD_TOOLS_VERSION}.`,
    );
  }
  return normalized;
}

function configuredToolVersions(mobileRoot, tools, execute = runTool) {
  const packageDocument = JSON.parse(readFileSync(join(mobileRoot, 'package.json'), 'utf8'));
  const gradleWrapper = loadReviewedGradleWrapper(mobileRoot);
  return Object.freeze({
    node: process.version,
    expo: boundedVersion(packageDocument.dependencies?.expo, 'Expo'),
    react_native: boundedVersion(packageDocument.dependencies?.['react-native'], 'React Native'),
    gradle_wrapper: boundedVersion(
      gradleWrapper.distributionUrl.split('/').at(-1),
      'Gradle wrapper',
    ),
    gradle_distribution_sha256: gradleWrapper.distributionSha256,
    android_build_tools: boundedVersion(basename(dirname(tools.apksigner)), 'Android Build Tools'),
    apksigner: boundedVersion(execute(tools.apksigner, ['version']), 'apksigner'),
    aapt2: parseReviewedAapt2Version(execute(
      tools.aapt2,
      ['version'],
      { successOutput: 'exclusive-stdout-or-stderr' },
    )),
  });
}

function canonicalLocalArtifactName({
  expectedAbi,
  gitHead,
  snapshotHash,
  versionCode,
  versionName,
  buildTimestamp,
}) {
  const safeVersion = versionName.replace(/[^A-Za-z0-9._-]+/g, '-').slice(0, 80);
  if (!safeVersion) throw new Error('Android version name cannot be used in an artifact filename.');
  const timestamp = new Date(buildTimestamp).toISOString().replace(/[-:.]/g, '');
  return [
    'global-connect-travels',
    `v${safeVersion}`,
    `vc${String(versionCode)}`,
    'local-signed-sideload',
    expectedAbi,
    gitHead.slice(0, 12),
    `src${snapshotHash.slice(0, 12).toLowerCase()}`,
    timestamp,
  ].join('-') + '.apk';
}

function normalizedBuildTimestamp(value) {
  const parsed = new Date(value);
  if (!value || Number.isNaN(parsed.getTime())) {
    throw new Error('Local Android build timestamp must be a valid ISO-8601 instant.');
  }
  return parsed.toISOString();
}

function assertArtifactBuiltAfter(artifact, buildTimestamp) {
  const buildStartedAtMs = Date.parse(buildTimestamp);
  if (
    !Number.isFinite(artifact?.mtimeMs)
    || artifact.mtimeMs < buildStartedAtMs
  ) {
    throw new Error('The Android artifact predates the declared local build start.');
  }
}

async function inspectLocalAndroidArtifact(options, dependencies = {}) {
  const artifactPath = resolve(options.artifactPath || '');
  if (!artifactPath.toLowerCase().endsWith('.apk')) {
    throw new Error('The local signed sideload artifact must be an APK.');
  }
  const artifact = statSync(artifactPath);
  if (!artifact.isFile() || artifact.size <= 0) {
    throw new Error('The local signed sideload artifact is empty or unavailable.');
  }
  assertAndroidArtifactSize('apk', artifact.size);
  const expectedAbis = expectedApkAbis(options.expectedAbi);
  const buildTimestamp = normalizedBuildTimestamp(options.buildTimestamp);
  assertArtifactBuiltAfter(artifact, buildTimestamp);
  const tools = dependencies.tools || resolveAndroidBuildTools(dependencies.environment);
  const execute = dependencies.runTool || runTool;
  const signer = parseApkSignerOutput(
    execute(tools.apksigner, ['verify', '--verbose', '--print-certs', artifactPath]),
  );
  const approvedFingerprints = options.approvedFingerprints instanceof Set
    ? options.approvedFingerprints
    : parseApprovedFingerprints(options.approvedFingerprints);
  if (!approvedFingerprints.has(signer)) {
    throw new Error('Local Android sideload signer is not in the approved distribution fingerprint set.');
  }
  const packageOutput = execute(tools.aapt2, ['dump', 'badging', artifactPath]);
  const packageMetadata = parsePackageMetadata(packageOutput);
  if (packageMetadata.packageName !== CANONICAL_ANDROID_PACKAGE) {
    throw new Error('Local Android sideload package does not match the canonical application.');
  }
  assertAndroidVersionMetadata(
    packageMetadata,
    options.expectedVersion,
    'Local Android sideload',
  );
  const nativeAbis = parseApkNativeAbis(packageOutput, expectedAbis);
  return Object.freeze({
    artifact_bytes: artifact.size,
    artifact_sha256: await (dependencies.sha256File || sha256File)(artifactPath),
    native_abis: nativeAbis,
    package_name: packageMetadata.packageName,
    signing_certificate_sha256: signer,
    version_code: packageMetadata.versionCode,
    version_name: packageMetadata.versionName,
  });
}

async function createLocalAndroidSideloadReceipt(options, dependencies = {}) {
  const artifactPath = resolve(options.artifactPath || '');
  const buildTimestamp = normalizedBuildTimestamp(options.buildTimestamp);
  const repoRoot = resolve(
    options.repoRoot || join(dirname(require.resolve('../package.json')), '..'),
  );
  const mobileRoot = join(repoRoot, 'mobile');
  const tools = dependencies.tools || resolveAndroidBuildTools(dependencies.environment);
  const execute = dependencies.runTool || runTool;
  const inspectedArtifact = await inspectLocalAndroidArtifact({
    artifactPath,
    buildTimestamp,
    expectedAbi: options.expectedAbi,
    approvedFingerprints: options.approvedFingerprints,
    expectedVersion: options.expectedVersion,
  }, { ...dependencies, runTool: execute, tools });
  const source = dependencies.sourceState || sourceState(repoRoot, dependencies);
  const snapshot = dependencies.sourceManifest || sourceManifest(repoRoot, dependencies);
  const toolVersions = dependencies.toolVersions
    || configuredToolVersions(mobileRoot, tools, execute);
  const generatedAt = (dependencies.now ? dependencies.now() : new Date()).toISOString();
  if (
    !options.stageEvidence
    || options.stageEvidence.manifest?.artifact_sha256 !== inspectedArtifact.artifact_sha256
    || options.stageEvidence.manifest?.native_android_snapshot?.sha256
      !== options.stageEvidence.nativeSnapshot?.sha256
    || options.stageEvidence.manifest?.build_config_fingerprint?.sha256
      !== options.stageEvidence.buildConfigFingerprint?.sha256
    || !/^[0-9A-F]{64}$/.test(options.stageEvidence.manifestSha256 || '')
  ) {
    throw new Error('Local sideload evidence must bind to the verified lane staging manifest.');
  }
  const canonicalArtifactFile = canonicalLocalArtifactName({
    expectedAbi: options.expectedAbi,
    gitHead: source.git_head,
    snapshotHash: snapshot.sha256,
    versionCode: inspectedArtifact.version_code,
    versionName: inspectedArtifact.version_name,
    buildTimestamp,
  });

  return Object.freeze({
    schema_version: 1,
    evidence_level: 'local_signed_sideload',
    release_eligible: false,
    provenance_scope: 'post_build_local_source_association_not_source_to_build_attestation',
    artifact_type: 'apk',
    source_artifact_file: basename(options.sourceArtifactFile || artifactPath),
    canonical_artifact_file: canonicalArtifactFile,
    artifact_bytes: inspectedArtifact.artifact_bytes,
    artifact_sha256: inspectedArtifact.artifact_sha256,
    package_name: inspectedArtifact.package_name,
    version_name: inspectedArtifact.version_name,
    version_code: inspectedArtifact.version_code,
    expected_source_version_name: options.expectedVersion.versionName,
    expected_source_version_code: options.expectedVersion.versionCode,
    version_evidence: 'aapt2_binary+checked_out_source+verified_staging_manifest',
    target_abi: options.expectedAbi,
    native_abis: inspectedArtifact.native_abis,
    signing_certificate_sha256: inspectedArtifact.signing_certificate_sha256,
    signing_assertion: 'valid_single_signer_v2_or_newer_and_approved_distribution_fingerprint',
    staging_manifest_file: basename(options.stageEvidence.manifestPath),
    staging_manifest_sha256: options.stageEvidence.manifestSha256,
    staging_source_artifact_sha256: options.stageEvidence.manifest.source_artifact_sha256,
    staging_temporary_artifact_sha256:
      options.stageEvidence.manifest.temporary_artifact_sha256,
    staged_artifact_sha256: options.stageEvidence.manifest.artifact_sha256,
    native_android_snapshot: options.stageEvidence.nativeSnapshot,
    build_config_fingerprint: options.stageEvidence.buildConfigFingerprint,
    build_timestamp_utc: buildTimestamp,
    receipt_generated_at_utc: generatedAt,
    source_dirty: source.repository_dirty,
    git_head: source.git_head,
    mobile_source_dirty: source.mobile_source_dirty,
    source_snapshot_timing: 'captured_after_artifact_build',
    mobile_source_snapshot: snapshot,
    tool_versions: toolVersions,
  });
}

async function materializeLocalAndroidSideload(options, dependencies = {}) {
  const sourceArtifactPath = resolve(options.artifactPath);
  const outputDirectory = resolve(options.outputDirectory || dirname(sourceArtifactPath));
  const outputMetadata = statSync(outputDirectory);
  if (!outputMetadata.isDirectory()) {
    throw new Error('The local sideload output path must be an existing directory.');
  }
  const buildTimestamp = normalizedBuildTimestamp(options.buildTimestamp);
  const approvedFingerprints = options.approvedFingerprints instanceof Set
    ? options.approvedFingerprints
    : parseApprovedFingerprints(
      options.approvedFingerprints
        ?? process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    );
  const expectedVersion = options.expectedVersion || loadAndroidSourceVersion();
  const stageEvidence = await verifyStagedAndroidApk({
    approvedFingerprints,
    artifactPath: sourceArtifactPath,
    expectedAbi: options.expectedAbi,
    expectedVersion,
    nativeSnapshot: options.nativeSnapshot,
    buildConfigFingerprint: options.buildConfigFingerprint,
  }, dependencies);
  const sourceMetadata = statSync(sourceArtifactPath);
  if (!sourceMetadata.isFile() || sourceMetadata.size <= 0) {
    throw new Error('The local signed sideload artifact is empty or unavailable.');
  }
  assertArtifactBuiltAfter(sourceMetadata, buildTimestamp);
  const temporaryArtifactPath = join(
    outputDirectory,
    `.local-sideload-partial-${randomUUID()}.apk`,
  );
  let canonicalArtifactPath;
  let receiptPath;
  let canonicalCreated = false;
  try {
    copyFileSync(sourceArtifactPath, temporaryArtifactPath, fsConstants.COPYFILE_EXCL);
    const receipt = await createLocalAndroidSideloadReceipt({
      ...options,
      approvedFingerprints,
      artifactPath: temporaryArtifactPath,
      buildTimestamp,
      expectedVersion,
      sourceArtifactFile: basename(sourceArtifactPath),
      stageEvidence,
    }, dependencies);
    const sourceHash = await (dependencies.sha256File || sha256File)(sourceArtifactPath);
    if (
      sourceMetadata.size !== receipt.artifact_bytes
      || sourceHash !== receipt.artifact_sha256
      || stageEvidence.manifest.artifact_sha256 !== receipt.artifact_sha256
    ) {
      throw new Error('The staged APK changed while its canonical copy was being created.');
    }
    canonicalArtifactPath = join(outputDirectory, receipt.canonical_artifact_file);
    receiptPath = `${canonicalArtifactPath}.receipt.json`;
    if (existsSync(canonicalArtifactPath) || existsSync(receiptPath)) {
      throw new Error('The canonical local sideload artifact or receipt already exists.');
    }
    copyFileSync(temporaryArtifactPath, canonicalArtifactPath, fsConstants.COPYFILE_EXCL);
    canonicalCreated = true;
    unlinkSync(temporaryArtifactPath);
    const finalArtifact = await inspectLocalAndroidArtifact({
      artifactPath: canonicalArtifactPath,
      buildTimestamp,
      expectedAbi: options.expectedAbi,
      approvedFingerprints,
      expectedVersion,
    }, dependencies);
    if (
      finalArtifact.artifact_bytes !== receipt.artifact_bytes
      || finalArtifact.artifact_sha256 !== receipt.artifact_sha256
      || finalArtifact.package_name !== receipt.package_name
      || finalArtifact.version_name !== receipt.version_name
      || finalArtifact.version_code !== receipt.version_code
      || finalArtifact.signing_certificate_sha256 !== receipt.signing_certificate_sha256
      || JSON.stringify(finalArtifact.native_abis) !== JSON.stringify(receipt.native_abis)
    ) {
      throw new Error('The final canonical sideload copy does not match its verified receipt.');
    }
    const finalStageEvidence = await verifyStagedAndroidApk({
      approvedFingerprints,
      artifactPath: sourceArtifactPath,
      buildConfigFingerprint: options.buildConfigFingerprint,
      expectedAbi: options.expectedAbi,
      expectedVersion,
      nativeSnapshot: options.nativeSnapshot,
    }, dependencies);
    if (
      finalStageEvidence.manifestSha256 !== stageEvidence.manifestSha256
      || finalStageEvidence.nativeSnapshot.sha256 !== stageEvidence.nativeSnapshot.sha256
      || finalStageEvidence.buildConfigFingerprint.sha256
        !== stageEvidence.buildConfigFingerprint.sha256
    ) {
      throw new Error('Local Android build inputs changed during canonical sideload packaging.');
    }
    writeFileSync(receiptPath, `${JSON.stringify(receipt, null, 2)}\n`, {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o600,
    });
    return Object.freeze({ canonicalArtifactPath, receiptPath, receipt });
  } catch (error) {
    if (existsSync(temporaryArtifactPath)) unlinkSync(temporaryArtifactPath);
    if (canonicalCreated && canonicalArtifactPath && existsSync(canonicalArtifactPath)) {
      unlinkSync(canonicalArtifactPath);
    }
    throw error;
  }
}

function parseCliArguments(args) {
  if (!Array.isArray(args) || args.length !== 4 || args.some((argument) => !argument)) {
    throw new Error(
      'Usage: package-local-android-sideload <apk> <existing-output-directory> <arm64-v8a|x86_64> <build-timestamp-utc>',
    );
  }
  const [artifactPath, outputDirectory, expectedAbi, buildTimestamp] = args;
  return Object.freeze({ artifactPath, outputDirectory, expectedAbi, buildTimestamp });
}

async function main() {
  assertProductionAndroidReleaseEvidenceEnvironment();
  const {
    artifactPath,
    outputDirectory,
    expectedAbi,
    buildTimestamp,
  } = parseCliArguments(process.argv.slice(2));
  const result = await materializeLocalAndroidSideload({
    approvedFingerprints: parseApprovedFingerprints(
      process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    ),
    artifactPath: resolveLaneStagedArtifactPath(artifactPath, expectedAbi, {
      action: 'verify',
    }),
    buildTimestamp,
    expectedAbi,
    expectedVersion: loadAndroidSourceVersion(),
    outputDirectory,
  });
  process.stdout.write(
    `Created local-only signed sideload evidence ${basename(result.canonicalArtifactPath)} with adjacent receipt ${basename(result.receiptPath)}.\n`,
  );
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

module.exports = {
  MOBILE_SOURCE_MANIFEST_EXCLUSIONS,
  REVIEWED_AAPT2_VERSION_OUTPUT,
  canonicalLocalArtifactName,
  configuredToolVersions,
  createLocalAndroidSideloadReceipt,
  inspectLocalAndroidArtifact,
  isExcludedMobileSourcePath,
  materializeLocalAndroidSideload,
  parseReviewedAapt2Version,
  parseCliArguments,
  sourceManifest,
  sourceState,
};
