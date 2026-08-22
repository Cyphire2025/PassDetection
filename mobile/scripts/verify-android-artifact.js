'use strict';

const { spawnSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { createReadStream, existsSync, statSync, writeFileSync } = require('node:fs');
const { basename, join, resolve } = require('node:path');

const CANONICAL_ANDROID_PACKAGE = 'com.globalconnects.groupcompanion';
const SHA256_HEX_PATTERN = /^[0-9A-F]{64}$/;
const BUILD_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const GIT_COMMIT_PATTERN = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i;

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

function parsePackageName(output) {
  if (typeof output !== 'string') throw new Error('Android package metadata is unavailable.');
  const match = output.match(/^package:\s+name='([^']+)'/m);
  if (!match || !/^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$/.test(match[1])) {
    throw new Error('Android package metadata is invalid.');
  }
  return match[1];
}

function versionParts(value) {
  return value.split('.').map((part) => Number.parseInt(part, 10) || 0);
}

function compareVersionsDescending(left, right) {
  const a = versionParts(left);
  const b = versionParts(right);
  for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
    const difference = (b[index] || 0) - (a[index] || 0);
    if (difference) return difference;
  }
  return 0;
}

function resolveAndroidBuildTools(source = process.env) {
  const directSigner = source.GC_APKSIGNER_PATH;
  const directAapt = source.GC_AAPT2_PATH;
  if (directSigner || directAapt) {
    if (!directSigner || !directAapt || !existsSync(directSigner) || !existsSync(directAapt)) {
      throw new Error('GC_APKSIGNER_PATH and GC_AAPT2_PATH must both reference existing files.');
    }
    return Object.freeze({ apksigner: directSigner, aapt2: directAapt });
  }

  const sdkRoot = source.ANDROID_HOME || source.ANDROID_SDK_ROOT;
  if (!sdkRoot) throw new Error('ANDROID_HOME or ANDROID_SDK_ROOT is required.');
  const buildToolsRoot = join(sdkRoot, 'build-tools');
  const { readdirSync } = require('node:fs');
  const versions = readdirSync(buildToolsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort(compareVersionsDescending);
  const executableSuffix = process.platform === 'win32' ? '.bat' : '';
  const aaptSuffix = process.platform === 'win32' ? '.exe' : '';
  for (const version of versions) {
    const apksigner = join(buildToolsRoot, version, `apksigner${executableSuffix}`);
    const aapt2 = join(buildToolsRoot, version, `aapt2${aaptSuffix}`);
    if (existsSync(apksigner) && existsSync(aapt2)) {
      return Object.freeze({ apksigner, aapt2 });
    }
  }
  throw new Error('A reviewed Android Build Tools installation with apksigner and aapt2 is required.');
}

function runTool(executable, args) {
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
  return result.stdout;
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

async function verifyAndroidArtifact(options, dependencies = {}) {
  const artifactPath = resolve(options.artifactPath || '');
  if (!artifactPath.toLowerCase().endsWith('.apk')) {
    throw new Error('The installable production verification artifact must be an APK.');
  }
  const artifact = statSync(artifactPath);
  if (!artifact.isFile() || artifact.size <= 0) throw new Error('Android artifact is empty or unavailable.');

  const expectedPackage = options.expectedPackage || CANONICAL_ANDROID_PACKAGE;
  if (expectedPackage !== CANONICAL_ANDROID_PACKAGE) {
    throw new Error('Android artifact must use the canonical production package.');
  }
  if (!BUILD_ID_PATTERN.test(options.buildId || '')) throw new Error('EAS build ID is invalid.');
  if (!GIT_COMMIT_PATTERN.test(options.gitCommitHash || '')) throw new Error('Build Git commit hash is invalid.');

  const approvedFingerprints = options.approvedFingerprints instanceof Set
    ? options.approvedFingerprints
    : parseApprovedFingerprints(options.approvedFingerprints);
  const tools = dependencies.tools || resolveAndroidBuildTools(dependencies.environment);
  const execute = dependencies.runTool || runTool;
  const signerOutput = execute(tools.apksigner, ['verify', '--verbose', '--print-certs', artifactPath]);
  const signingCertificateSha256 = parseApkSignerOutput(signerOutput);
  if (!approvedFingerprints.has(signingCertificateSha256)) {
    throw new Error('Android artifact signer is not in the approved production fingerprint set.');
  }
  const packageOutput = execute(tools.aapt2, ['dump', 'badging', artifactPath]);
  const packageName = parsePackageName(packageOutput);
  if (packageName !== expectedPackage) throw new Error('Android artifact package does not match production.');

  return Object.freeze({
    schema_version: 1,
    artifact_type: 'apk',
    artifact_file: basename(artifactPath),
    artifact_bytes: artifact.size,
    artifact_sha256: await sha256File(artifactPath),
    package_name: packageName,
    signing_certificate_sha256: signingCertificateSha256,
    eas_build_id: options.buildId.toLowerCase(),
    git_commit_hash: options.gitCommitHash.toLowerCase(),
  });
}

async function main() {
  const [artifactPath, receiptPath, buildId, gitCommitHash] = process.argv.slice(2);
  if (!artifactPath || !receiptPath || !buildId || !gitCommitHash) {
    throw new Error('Usage: verify-android-artifact <apk> <receipt.json> <eas-build-id> <git-commit-hash>');
  }
  const receipt = await verifyAndroidArtifact({
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(
      process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    ),
    buildId,
    expectedPackage: CANONICAL_ANDROID_PACKAGE,
    gitCommitHash,
  });
  writeFileSync(resolve(receiptPath), `${JSON.stringify(receipt, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
    mode: 0o600,
  });
  process.stdout.write(
    `Verified ${receipt.package_name} production APK; receipt SHA-256 ${receipt.artifact_sha256}.\n`,
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
  normalizeFingerprint,
  parseApprovedFingerprints,
  parseApkSignerOutput,
  parsePackageName,
  resolveAndroidBuildTools,
  verifyAndroidArtifact,
};
