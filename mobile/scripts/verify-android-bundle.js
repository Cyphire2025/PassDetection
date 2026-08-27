'use strict';

const { spawnSync } = require('node:child_process');
const { existsSync, lstatSync, statSync, writeFileSync } = require('node:fs');
const { join, resolve } = require('node:path');

const {
  CANONICAL_ANDROID_PACKAGE,
  normalizeFingerprint,
  parseApprovedFingerprints,
} = require('./verify-android-artifact');
const {
  ANDROID_PLAY_BUNDLE_ABIS,
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

const BUILD_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const BUNDLETOOL_VERSION = '1.18.3';
const BUNDLETOOL_SHA256 = 'A099CFA1543F55593BC2ED16A70A7C67FE54B1747BB7301F37FDFD6D91028E29';

function resolveJavaTools(source = process.env) {
  const javaHome = source.JAVA_HOME;
  if (!javaHome) throw new Error('JAVA_HOME is required to verify the Android App Bundle.');
  const suffix = process.platform === 'win32' ? '.exe' : '';
  const tools = {
    java: join(javaHome, 'bin', `java${suffix}`),
    jar: join(javaHome, 'bin', `jar${suffix}`),
    jarsigner: join(javaHome, 'bin', `jarsigner${suffix}`),
    keytool: join(javaHome, 'bin', `keytool${suffix}`),
  };
  if (Object.values(tools).some((tool) => !existsSync(tool))) {
    throw new Error('JAVA_HOME must provide java, jar, jarsigner, and keytool.');
  }
  return Object.freeze(tools);
}

function runTool(executable, args) {
  const result = spawnSync(executable, args, {
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
    shell: false,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Android App Bundle verification tool failed with exit ${String(result.status)}.`);
  }
  return `${result.stdout || ''}\n${result.stderr || ''}`;
}

function parseBundleSignatureEntries(output) {
  if (typeof output !== 'string') throw new Error('Android App Bundle entries are unavailable.');
  const entries = output
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .filter((entry) => /^META-INF\/[^/]+\.(?:RSA|DSA|EC)$/i.test(entry));
  if (entries.length !== 1) {
    throw new Error('Android App Bundle must contain exactly one archive signer block.');
  }
  return entries[0];
}

function parseBundleNativeAbiEvidence(output) {
  if (typeof output !== 'string') {
    throw new Error('Android App Bundle native ABI metadata is unavailable.');
  }
  const modules = new Map();
  const caseInsensitiveModuleNames = new Map();
  for (const rawEntry of output.split(/\r?\n/)) {
    const entry = rawEntry.trim();
    if (!entry || !/(?:^|\/)lib\//i.test(entry) || !/\.so$/i.test(entry)) continue;
    const match = entry.match(/^([^/]+)\/lib\/([^/]+)\/([^/]+\.so)$/i);
    if (!match) {
      throw new Error('Android App Bundle native library path is invalid.');
    }
    const [, moduleName, abi] = match;
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(moduleName)) {
      throw new Error('Android App Bundle native module name is invalid.');
    }
    const foldedModuleName = moduleName.toLowerCase();
    const existingModuleName = caseInsensitiveModuleNames.get(foldedModuleName);
    if (existingModuleName && existingModuleName !== moduleName) {
      throw new Error('Android App Bundle native module names are ambiguous.');
    }
    caseInsensitiveModuleNames.set(foldedModuleName, moduleName);
    if (!modules.has(moduleName)) modules.set(moduleName, new Set());
    modules.get(moduleName).add(abi);
  }
  if (modules.size === 0) {
    throw new Error('Production Android App Bundle does not declare any native ABIs.');
  }
  const moduleNativeAbis = {};
  for (const [moduleName, abis] of [...modules.entries()].sort(([left], [right]) => (
    left.localeCompare(right)
  ))) {
    moduleNativeAbis[moduleName] = assertExactAndroidAbis(
      [...abis],
      ANDROID_PLAY_BUNDLE_ABIS,
      `Production Android App Bundle module ${moduleName}`,
    );
  }
  return Object.freeze({
    moduleNativeAbis: Object.freeze(moduleNativeAbis),
    nativeAbis: assertExactAndroidAbis(
      [...new Set(Object.values(moduleNativeAbis).flat())],
      ANDROID_PLAY_BUNDLE_ABIS,
      'Production Android App Bundle',
    ),
  });
}

function parseBundleNativeAbis(output) {
  return parseBundleNativeAbiEvidence(output).nativeAbis;
}

function parseBundleCertificate(output) {
  if (typeof output !== 'string') throw new Error('Android App Bundle certificate is unavailable.');
  if (/^Owner:\s*[^\r\n]*\bAndroid Debug\b/im.test(output)) {
    throw new Error('Android App Bundle is signed with a debug certificate.');
  }
  const fingerprints = new Set(
    [...output.matchAll(/^\s*SHA256:\s*([0-9A-F:]+)\s*$/gim)]
      .map((match) => normalizeFingerprint(match[1], 'App Bundle signing certificate')),
  );
  if (fingerprints.size !== 1) {
    throw new Error('Android App Bundle must expose exactly one SHA-256 signing certificate.');
  }
  return [...fingerprints][0];
}

function assertBundleArchiveVerification(output) {
  if (typeof output !== 'string') {
    throw new Error('Android App Bundle archive signature verification is unavailable.');
  }
  if (!/^\s*jar verified\.\s*$/im.test(output)) {
    throw new Error('Android App Bundle archive signature was not verified.');
  }
  if (/\b(?:jar is unsigned|unsigned entries|not integrity-checked)\b/i.test(output)) {
    throw new Error('Android App Bundle contains unsigned archive entries.');
  }
}

function parseBundleManifestValue(output, label) {
  if (typeof output !== 'string') throw new Error(`Android App Bundle ${label} is unavailable.`);
  const value = output.trim();
  if (!value || value.includes('\n') || value.includes('\r') || value.length > 200) {
    throw new Error(`Android App Bundle ${label} is invalid.`);
  }
  return value;
}

function parseBundleManifestMetadata({ packageName, versionCode, versionName }) {
  const parsedPackageName = parseBundleManifestValue(packageName, 'manifest package name');
  if (!/^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$/.test(parsedPackageName)) {
    throw new Error('Android App Bundle manifest package name is invalid.');
  }
  return Object.freeze({
    packageName: parsedPackageName,
    versionCode: positiveVersionCode(
      parseBundleManifestValue(versionCode, 'manifest version code'),
      'Android App Bundle manifest',
    ),
    versionName: boundedVersionName(
      parseBundleManifestValue(versionName, 'manifest version name'),
      'Android App Bundle manifest',
    ),
  });
}

function resolveBundletoolPath(options, dependencies) {
  const environment = dependencies.environment || process.env;
  const configuredPath = options.bundletoolPath || environment.GC_ANDROID_BUNDLETOOL_JAR_PATH;
  if (!configuredPath) {
    if (options.requireBinaryManifest === false) return null;
    throw new Error('GC_ANDROID_BUNDLETOOL_JAR_PATH is required for release-eligible AAB verification.');
  }
  const bundletoolPath = resolve(configuredPath);
  const bundletool = lstatSync(bundletoolPath);
  if (
    bundletool.isSymbolicLink()
    || !bundletool.isFile()
    || bundletool.size <= 0
    || !bundletoolPath.toLowerCase().endsWith('.jar')
  ) {
    throw new Error('Pinned bundletool must be a non-empty regular JAR file, not a symbolic link.');
  }
  return bundletoolPath;
}

async function inspectBundleManifest(options, dependencies, tools, execute) {
  const bundletoolPath = resolveBundletoolPath(options, dependencies);
  if (!bundletoolPath) return null;
  const snapshot = await createArtifactSnapshot(bundletoolPath, '.jar', {
    sha256File: dependencies.bundletoolSha256File,
  });
  try {
    if (snapshot.artifactSha256 !== BUNDLETOOL_SHA256) {
      throw new Error(`Pinned bundletool ${BUNDLETOOL_VERSION} checksum is invalid.`);
    }
    const versionOutput = execute(
      tools.java,
      ['-jar', snapshot.snapshotPath, 'version'],
    ).trim();
    if (versionOutput !== BUNDLETOOL_VERSION) {
      throw new Error(`Pinned bundletool must report version ${BUNDLETOOL_VERSION}.`);
    }
    const dumpValue = (xpath) => execute(tools.java, [
      '-jar',
      snapshot.snapshotPath,
      'dump',
      'manifest',
      `--bundle=${options.artifactPath}`,
      `--xpath=${xpath}`,
    ]);
    const metadata = parseBundleManifestMetadata({
      packageName: dumpValue('/manifest/@package'),
      versionCode: dumpValue('/manifest/@android:versionCode'),
      versionName: dumpValue('/manifest/@android:versionName'),
    });
    await snapshot.assertStable();
    return Object.freeze({
      metadata,
      sha256: snapshot.artifactSha256,
      version: BUNDLETOOL_VERSION,
    });
  } finally {
    snapshot.cleanup();
  }
}

async function inspectAndroidBundle(options, dependencies = {}) {
  const artifactPath = resolve(options.artifactPath || '');
  if (!artifactPath.toLowerCase().endsWith('.aab')) {
    throw new Error('The Android store artifact must be an AAB.');
  }
  const artifact = statSync(artifactPath);
  if (!artifact.isFile() || artifact.size <= 0) throw new Error('Android App Bundle is empty or unavailable.');
  assertAndroidArtifactSize('aab', artifact.size);
  const approvedFingerprints = options.approvedFingerprints instanceof Set
    ? options.approvedFingerprints
    : parseApprovedFingerprints(options.approvedFingerprints);
  const tools = dependencies.tools || resolveJavaTools(dependencies.environment);
  const execute = dependencies.runTool || runTool;
  const archiveEntries = execute(tools.jar, ['tf', artifactPath]);
  parseBundleSignatureEntries(archiveEntries);
  const abiEvidence = parseBundleNativeAbiEvidence(archiveEntries);
  const verificationOutput = execute(
    tools.jarsigner,
    ['-verify', '-verbose', '-certs', artifactPath],
  );
  assertBundleArchiveVerification(verificationOutput);
  const signingCertificateSha256 = parseBundleCertificate(
    execute(tools.keytool, ['-printcert', '-jarfile', artifactPath]),
  );
  if (!approvedFingerprints.has(signingCertificateSha256)) {
    throw new Error('Android App Bundle signer is not in the approved distribution fingerprint set.');
  }
  const manifestInspection = await inspectBundleManifest(
    { ...options, artifactPath },
    dependencies,
    tools,
    execute,
  );

  return Object.freeze({
    artifact_bytes: artifact.size,
    artifact_sha256: await (dependencies.sha256File || sha256File)(artifactPath),
    module_native_abis: abiEvidence.moduleNativeAbis,
    native_abis: abiEvidence.nativeAbis,
    signing_certificate_sha256: signingCertificateSha256,
    manifest_metadata: manifestInspection?.metadata || null,
    manifest_tool: manifestInspection
      ? Object.freeze({
        name: 'bundletool',
        sha256: manifestInspection.sha256,
        version: manifestInspection.version,
      })
      : null,
  });
}

async function verifyAndroidBundle(options, dependencies = {}) {
  const artifactPath = resolve(options.artifactPath || '');
  if (options.appIdentifier !== CANONICAL_ANDROID_PACKAGE) {
    throw new Error('EAS build metadata does not identify the canonical production package.');
  }
  if (!BUILD_ID_PATTERN.test(options.buildId || '')) throw new Error('EAS build ID is invalid.');
  const provenance = verifyReleaseProvenance(options, dependencies);
  const sourceVersionName = boundedVersionName(
    options.expectedSourceVersion?.versionName,
    'Checked-out source',
  );
  const sourceVersionCode = positiveVersionCode(
    options.expectedSourceVersion?.versionCode,
    'Checked-out source',
  );
  const appVersion = boundedVersionName(options.appVersion, 'EAS build metadata');
  const appBuildVersion = positiveVersionCode(options.appBuildVersion, 'EAS build metadata');
  if (appVersion !== sourceVersionName || appBuildVersion !== sourceVersionCode) {
    throw new Error('EAS App Bundle version does not match checked-out source.');
  }
  const snapshot = await (dependencies.createArtifactSnapshot || createArtifactSnapshot)(
    artifactPath,
    '.aab',
    { sha256File: dependencies.sha256File },
  );
  try {
    const inspected = await inspectAndroidBundle({
      ...options,
      artifactPath: snapshot.snapshotPath,
      requireBinaryManifest: true,
    }, dependencies);
    const binaryMetadata = inspected.manifest_metadata;
    if (
      !binaryMetadata
      || binaryMetadata.packageName !== CANONICAL_ANDROID_PACKAGE
      || binaryMetadata.packageName !== options.appIdentifier
    ) {
      throw new Error('Android App Bundle binary package does not match production and EAS metadata.');
    }
    if (
      binaryMetadata.versionName !== sourceVersionName
      || binaryMetadata.versionName !== appVersion
      || binaryMetadata.versionCode !== sourceVersionCode
      || binaryMetadata.versionCode !== appBuildVersion
    ) {
      throw new Error('Android App Bundle binary version does not match checked-out source and EAS build metadata.');
    }
    await snapshot.assertStable();

    return Object.freeze({
      schema_version: 3,
      artifact_type: 'aab',
      artifact_file: snapshot.originalFile,
      canonical_artifact_file: canonicalAndroidArtifactName({
        type: 'aab',
        buildId: options.buildId,
        gitCommitHash: provenance.gitCommitHash,
      }),
      artifact_bytes: snapshot.artifactBytes,
      artifact_sha256: snapshot.artifactSha256,
      native_abis: inspected.native_abis,
      module_native_abis: inspected.module_native_abis,
      package_name: binaryMetadata.packageName,
      package_evidence: `bundletool_${BUNDLETOOL_VERSION}_binary_manifest`,
      version_name: binaryMetadata.versionName,
      version_code: binaryMetadata.versionCode,
      source_version_name: sourceVersionName,
      source_version_code: sourceVersionCode,
      version_evidence: `version_name_and_code=bundletool_${BUNDLETOOL_VERSION}_binary_manifest+eas_build_metadata+checked_out_source; eas_local_version_source; auto_increment_disabled`,
      manifest_tool: inspected.manifest_tool,
      signing_certificate_sha256: inspected.signing_certificate_sha256,
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
    throw new Error(
      'Usage: verify-android-bundle <aab> <receipt.json> <eas-build-id> <git-commit-hash> <source-fingerprint-hash> <app-identifier> <eas-app-version> <eas-build-version>',
    );
  }
  const [
    artifactPath,
    receiptPath,
    buildId,
    gitCommitHash,
    sourceFingerprintHash,
    appIdentifier,
    appVersion,
    appBuildVersion,
  ] = args;
  return Object.freeze({
    appBuildVersion,
    appIdentifier,
    appVersion,
    artifactPath,
    buildId,
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
    appIdentifier,
    appVersion,
    appBuildVersion,
  } = parseCliArguments(process.argv.slice(2));
  const receipt = await verifyAndroidBundle({
    appBuildVersion,
    appIdentifier,
    appVersion,
    approvedFingerprints: parseApprovedFingerprints(
      process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    ),
    artifactPath,
    buildId,
    gitCommitHash,
    sourceFingerprintHash,
    expectedSourceVersion: loadAndroidSourceVersion(),
  });
  writeFileSync(resolve(receiptPath), `${JSON.stringify(receipt, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
    mode: 0o600,
  });
  process.stdout.write(
    `Verified ${receipt.package_name} production AAB; preserve it as ${receipt.canonical_artifact_file}; receipt SHA-256 ${receipt.artifact_sha256}.\n`,
  );
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

module.exports = {
  BUNDLETOOL_SHA256,
  BUNDLETOOL_VERSION,
  assertBundleArchiveVerification,
  inspectAndroidBundle,
  parseBundleManifestMetadata,
  parseBundleCertificate,
  parseBundleNativeAbiEvidence,
  parseBundleNativeAbis,
  parseBundleSignatureEntries,
  parseCliArguments,
  resolveJavaTools,
  verifyAndroidBundle,
};
