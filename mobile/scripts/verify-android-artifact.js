'use strict';

const { spawnSync } = require('node:child_process');
const { existsSync, lstatSync, writeFileSync } = require('node:fs');
const { basename, dirname, join, resolve } = require('node:path');

const {
  ANDROID_ARM64_APK_ABIS,
  ANDROID_X86_64_APK_ABIS,
  assertAndroidArtifactSize,
  assertExactAndroidAbis,
  canonicalAndroidArtifactName,
} = require('./android-release-policy');
const {
  boundedVersionName,
  loadAndroidSourceVersion,
  positiveVersionCode,
} = require('./android-release-source-version');
const {
  createArtifactSnapshot,
  sha256File,
} = require('./android-artifact-snapshot');
const { verifyReleaseProvenance } = require('./android-release-provenance');
const {
  REVIEWED_ANDROID_BUILD_TOOLS_VERSION,
} = require('./android-release-toolchain');

const CANONICAL_ANDROID_PACKAGE = 'com.globalconnects.groupcompanion';
const SHA256_HEX_PATTERN = /^[0-9A-F]{64}$/;
const BUILD_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function normalizeFingerprint(value, source = 'certificate fingerprint') {
  if (typeof value !== 'string') throw new Error(`${source} is invalid.`);
  const hex = value.trim().replaceAll(':', '').toUpperCase();
  if (!SHA256_HEX_PATTERN.test(hex)) {
    throw new Error(`${source} must be a SHA-256 certificate fingerprint.`);
  }
  return hex.match(/.{2}/g).join(':');
}

function parseApprovedFingerprints(
  value,
  source = 'GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS',
) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${source} is required.`);
  }
  if (value.length > 4_096) {
    throw new Error(`${source} must be at most 4096 characters.`);
  }
  const entries = value.split(',').map((entry, index) => (
    normalizeFingerprint(entry, `approved certificate fingerprint ${index + 1}`)
  ));
  if (entries.length > 5) {
    throw new Error('Approved Android certificate fingerprint rotation is limited to five entries.');
  }
  if (entries.length !== new Set(entries).size) {
    throw new Error('Approved Android certificate fingerprints must be unique.');
  }
  return new Set(entries);
}

function parseApkSignerOutput(output) {
  if (typeof output !== 'string' || !/\bVerifies\b/i.test(output)) {
    throw new Error('Android artifact signature verification did not produce a valid result.');
  }
  if (/certificate DN:\s*[^\r\n]*\bAndroid Debug\b/i.test(output)) {
    throw new Error('Android artifact is signed with a debug certificate.');
  }
  if (!/Verified using v(?:2|3(?:\.1|\.2)?|4) scheme[^\r\n]*:\s*true/i.test(output)) {
    throw new Error('Android artifact must use APK Signature Scheme v2 or newer.');
  }

  const declaredSignerCount = output.match(/Number of signers:\s*(\d+)/i);
  if (!declaredSignerCount || Number(declaredSignerCount[1]) !== 1) {
    throw new Error('Android artifact must contain exactly one signer.');
  }
  const fingerprints = new Set(
    [...output.matchAll(/certificate SHA-256 digest:\s*([0-9a-f:]+)/gi)]
      .map((match) => normalizeFingerprint(match[1], 'artifact signing certificate')),
  );
  if (fingerprints.size !== 1) {
    throw new Error('Android artifact must expose exactly one signing certificate.');
  }
  return [...fingerprints][0];
}

function parsePackageMetadata(output) {
  if (typeof output !== 'string') throw new Error('Android package metadata is unavailable.');
  const match = output.match(
    /^package:\s+name='([^']+)'\s+versionCode='([0-9]+)'\s+versionName='([^']+)'/m,
  );
  if (!match || !/^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$/.test(match[1])) {
    throw new Error('Android package metadata is invalid.');
  }
  const versionCode = Number(match[2]);
  if (!Number.isSafeInteger(versionCode) || versionCode <= 0 || match[3].length > 100) {
    throw new Error('Android package version metadata is invalid.');
  }
  return Object.freeze({
    packageName: match[1],
    versionCode,
    versionName: match[3],
  });
}

function parsePackageName(output) {
  return parsePackageMetadata(output).packageName;
}

function expectedApkAbis(value) {
  if (value === 'arm64-v8a') return ANDROID_ARM64_APK_ABIS;
  if (value === 'x86_64') return ANDROID_X86_64_APK_ABIS;
  throw new Error('Production APK verification target must equal arm64-v8a or x86_64.');
}

function parseApkNativeAbis(output, expected = ANDROID_ARM64_APK_ABIS) {
  if (typeof output !== 'string') {
    throw new Error('Android package native ABI metadata is unavailable.');
  }
  const match = output.match(/^native-code:\s*(.*)$/m);
  const abis = match ? [...match[1].matchAll(/'([^']+)'/g)].map((entry) => entry[1]) : [];
  return assertExactAndroidAbis(abis, expected, 'Production APK');
}

function assertReviewedBuildToolFile(filePath, expectedName) {
  if (!existsSync(filePath)) {
    throw new Error(
      `Reviewed Android Build Tools ${REVIEWED_ANDROID_BUILD_TOOLS_VERSION} `
      + `must provide ${expectedName}.`,
    );
  }
  const metadata = lstatSync(filePath);
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw new Error(
      `Reviewed Android Build Tools ${REVIEWED_ANDROID_BUILD_TOOLS_VERSION} `
      + `${expectedName} must be a regular file, not a symbolic link.`,
    );
  }
}

function reviewedAndroidBuildTools(apksignerPath, aapt2Path) {
  const apksigner = resolve(apksignerPath);
  const aapt2 = resolve(aapt2Path);
  const signerDirectory = dirname(apksigner);
  const aaptDirectory = dirname(aapt2);
  const normalizedSignerDirectory = process.platform === 'win32'
    ? signerDirectory.toLowerCase()
    : signerDirectory;
  const normalizedAaptDirectory = process.platform === 'win32'
    ? aaptDirectory.toLowerCase()
    : aaptDirectory;
  if (
    normalizedSignerDirectory !== normalizedAaptDirectory
    || basename(signerDirectory) !== REVIEWED_ANDROID_BUILD_TOOLS_VERSION
  ) {
    throw new Error(
      `Android artifact verification requires both tools from reviewed Android `
      + `Build Tools ${REVIEWED_ANDROID_BUILD_TOOLS_VERSION}.`,
    );
  }
  assertReviewedBuildToolFile(apksigner, 'apksigner');
  assertReviewedBuildToolFile(aapt2, 'aapt2');
  return Object.freeze({
    aapt2,
    apksigner,
    version: REVIEWED_ANDROID_BUILD_TOOLS_VERSION,
  });
}

function resolveAndroidBuildTools(source = process.env) {
  const directSigner = source.GC_APKSIGNER_PATH;
  const directAapt = source.GC_AAPT2_PATH;
  if (directSigner || directAapt) {
    if (!directSigner || !directAapt) {
      throw new Error(
        `GC_APKSIGNER_PATH and GC_AAPT2_PATH must both reference reviewed Android `
        + `Build Tools ${REVIEWED_ANDROID_BUILD_TOOLS_VERSION}.`,
      );
    }
    return reviewedAndroidBuildTools(directSigner, directAapt);
  }

  const sdkRoot = source.ANDROID_HOME || source.ANDROID_SDK_ROOT;
  if (!sdkRoot) throw new Error('ANDROID_HOME or ANDROID_SDK_ROOT is required.');
  const executableSuffix = process.platform === 'win32' ? '.bat' : '';
  const aaptSuffix = process.platform === 'win32' ? '.exe' : '';
  const reviewedDirectory = join(
    sdkRoot,
    'build-tools',
    REVIEWED_ANDROID_BUILD_TOOLS_VERSION,
  );
  return reviewedAndroidBuildTools(
    join(reviewedDirectory, `apksigner${executableSuffix}`),
    join(reviewedDirectory, `aapt2${aaptSuffix}`),
  );
}

function successfulToolOutput(result, mode = 'stdout') {
  const stdout = String(result.stdout || '');
  const stderr = String(result.stderr || '');
  if (mode === 'stdout') return stdout;
  if (mode !== 'exclusive-stdout-or-stderr') {
    throw new Error('Android artifact verification tool output mode is invalid.');
  }
  const hasStdout = Boolean(stdout.trim());
  const hasStderr = Boolean(stderr.trim());
  if (hasStdout && hasStderr) {
    throw new Error('Android artifact verification tool emitted ambiguous successful output.');
  }
  return hasStdout ? stdout : stderr;
}

function runTool(executable, args, options = {}) {
  let command = executable;
  let commandArgs = args;
  const windowsBatch = process.platform === 'win32' && executable.toLowerCase().endsWith('.bat');
  if (windowsBatch) {
    const commandParts = [executable, ...args];
    if (commandParts.some((part) => /["&|<>^%!\r\n]/.test(part))) {
      throw new Error('Android verification paths contain unsafe Windows command characters.');
    }
    command = process.env.ComSpec || 'cmd.exe';
    commandArgs = [
      '/d',
      '/s',
      '/c',
      `""${executable}" ${args.map((argument) => `"${argument}"`).join(' ')}"`,
    ];
  }
  const result = spawnSync(command, commandArgs, {
    encoding: 'utf8',
    maxBuffer: 16 * 1024 * 1024,
    shell: false,
    windowsVerbatimArguments: windowsBatch,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Android artifact verification tool failed with exit ${String(result.status)}.`);
  }
  return successfulToolOutput(result, options.successOutput);
}

async function verifyAndroidArtifact(options, dependencies = {}) {
  const artifactPath = resolve(options.artifactPath || '');
  if (!artifactPath.toLowerCase().endsWith('.apk')) {
    throw new Error('The installable production verification artifact must be an APK.');
  }

  const expectedPackage = options.expectedPackage || CANONICAL_ANDROID_PACKAGE;
  if (expectedPackage !== CANONICAL_ANDROID_PACKAGE) {
    throw new Error('Android artifact must use the canonical production package.');
  }
  if (!BUILD_ID_PATTERN.test(options.buildId || '')) throw new Error('EAS build ID is invalid.');
  const provenance = verifyReleaseProvenance(options, dependencies);

  const approvedFingerprints = options.approvedFingerprints instanceof Set
    ? options.approvedFingerprints
    : parseApprovedFingerprints(options.approvedFingerprints);
  const snapshot = await (dependencies.createArtifactSnapshot || createArtifactSnapshot)(
    artifactPath,
    '.apk',
    { sha256File: dependencies.sha256File },
  );
  try {
    assertAndroidArtifactSize('apk', snapshot.artifactBytes);
    const tools = dependencies.tools || resolveAndroidBuildTools(dependencies.environment);
    const execute = dependencies.runTool || runTool;
    const signerOutput = execute(
      tools.apksigner,
      ['verify', '--verbose', '--print-certs', snapshot.snapshotPath],
    );
    const signingCertificateSha256 = parseApkSignerOutput(signerOutput);
    if (!approvedFingerprints.has(signingCertificateSha256)) {
      throw new Error('Android artifact signer is not in the approved production fingerprint set.');
    }
    const packageOutput = execute(tools.aapt2, ['dump', 'badging', snapshot.snapshotPath]);
    const packageMetadata = parsePackageMetadata(packageOutput);
    if (packageMetadata.packageName !== expectedPackage) {
      throw new Error('Android artifact package does not match production.');
    }
    const expectedSourceVersion = options.expectedSourceVersion;
    const sourceVersionName = boundedVersionName(
      expectedSourceVersion?.versionName,
      'Checked-out source',
    );
    const sourceVersionCode = positiveVersionCode(
      expectedSourceVersion?.versionCode,
      'Checked-out source',
    );
    const easAppVersion = boundedVersionName(options.appVersion, 'EAS build metadata');
    const easBuildVersion = positiveVersionCode(options.appBuildVersion, 'EAS build metadata');
    if (
      packageMetadata.versionName !== sourceVersionName
      || packageMetadata.versionName !== easAppVersion
      || packageMetadata.versionCode !== easBuildVersion
      || packageMetadata.versionCode !== sourceVersionCode
    ) {
      throw new Error('Android artifact version does not match checked-out source and EAS build metadata.');
    }
    const expectedNativeAbis = options.expectedAbis
      || expectedApkAbis(options.expectedAbi || 'arm64-v8a');
    const nativeAbis = parseApkNativeAbis(packageOutput, expectedNativeAbis);
    await snapshot.assertStable();

    return Object.freeze({
      schema_version: 3,
      artifact_type: 'apk',
      artifact_file: snapshot.originalFile,
      canonical_artifact_file: canonicalAndroidArtifactName({
        type: 'apk',
        buildId: options.buildId,
        gitCommitHash: provenance.gitCommitHash,
        nativeAbis,
      }),
      artifact_bytes: snapshot.artifactBytes,
      artifact_sha256: snapshot.artifactSha256,
      native_abis: nativeAbis,
      package_name: packageMetadata.packageName,
      version_name: packageMetadata.versionName,
      version_code: packageMetadata.versionCode,
      source_version_name: sourceVersionName,
      source_version_code: sourceVersionCode,
      version_evidence: 'version_name_and_code=aapt2_binary+eas_build_metadata+checked_out_source; eas_local_version_source; auto_increment_disabled',
      signing_certificate_sha256: signingCertificateSha256,
      eas_build_id: options.buildId.toLowerCase(),
      git_commit_hash: provenance.gitCommitHash,
      source_fingerprint_hash: provenance.sourceFingerprintHash,
    });
  } finally {
    snapshot.cleanup();
  }
}

function parseCliArguments(args) {
  if (!Array.isArray(args) || args.length !== 8 || args.some((argument) => !argument)) {
    throw new Error('Usage: verify-android-artifact <apk> <receipt.json> <eas-build-id> <git-commit-hash> <source-fingerprint-hash> <arm64-v8a|x86_64> <eas-app-version> <eas-build-version>');
  }
  const [
    artifactPath,
    receiptPath,
    buildId,
    gitCommitHash,
    sourceFingerprintHash,
    expectedAbi,
    appVersion,
    appBuildVersion,
  ] = args;
  return Object.freeze({
    appBuildVersion,
    appVersion,
    artifactPath,
    buildId,
    expectedAbi,
    gitCommitHash,
    receiptPath,
    sourceFingerprintHash,
  });
}

async function main() {
  const {
    artifactPath,
    receiptPath,
    buildId,
    gitCommitHash,
    sourceFingerprintHash,
    expectedAbi,
    appVersion,
    appBuildVersion,
  } = parseCliArguments(process.argv.slice(2));
  const receipt = await verifyAndroidArtifact({
    appBuildVersion,
    appVersion,
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(
      process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    ),
    buildId,
    expectedPackage: CANONICAL_ANDROID_PACKAGE,
    expectedAbi,
    expectedSourceVersion: loadAndroidSourceVersion(),
    gitCommitHash,
    sourceFingerprintHash,
  });
  writeFileSync(resolve(receiptPath), `${JSON.stringify(receipt, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
    mode: 0o600,
  });
  process.stdout.write(
    `Verified ${receipt.package_name} production APK; preserve it as ${receipt.canonical_artifact_file}; receipt SHA-256 ${receipt.artifact_sha256}.\n`,
  );
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

module.exports = {
  CANONICAL_ANDROID_PACKAGE,
  REVIEWED_ANDROID_BUILD_TOOLS_VERSION,
  expectedApkAbis,
  normalizeFingerprint,
  parseApprovedFingerprints,
  parseApkNativeAbis,
  parseApkSignerOutput,
  parseCliArguments,
  parsePackageMetadata,
  parsePackageName,
  runTool,
  resolveAndroidBuildTools,
  sha256File,
  successfulToolOutput,
  verifyAndroidArtifact,
};
