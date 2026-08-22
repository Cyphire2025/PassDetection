'use strict';

const { spawnSync } = require('node:child_process');
const { createHash } = require('node:crypto');
const { createReadStream, existsSync, statSync, writeFileSync } = require('node:fs');
const { basename, join, resolve } = require('node:path');

const {
  CANONICAL_ANDROID_PACKAGE,
  normalizeFingerprint,
  parseApprovedFingerprints,
} = require('./verify-android-artifact');

const BUILD_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const GIT_COMMIT_PATTERN = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i;

function resolveJavaTools(source = process.env) {
  const javaHome = source.JAVA_HOME;
  if (!javaHome) throw new Error('JAVA_HOME is required to verify the Android App Bundle.');
  const suffix = process.platform === 'win32' ? '.exe' : '';
  const tools = {
    jar: join(javaHome, 'bin', `jar${suffix}`),
    jarsigner: join(javaHome, 'bin', `jarsigner${suffix}`),
    keytool: join(javaHome, 'bin', `keytool${suffix}`),
  };
  if (Object.values(tools).some((tool) => !existsSync(tool))) {
    throw new Error('JAVA_HOME must provide jar, jarsigner, and keytool.');
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

function sha256File(filePath) {
  return new Promise((resolveHash, reject) => {
    const digest = createHash('sha256');
    const stream = createReadStream(filePath);
    stream.on('error', reject);
    stream.on('data', (chunk) => digest.update(chunk));
    stream.on('end', () => resolveHash(digest.digest('hex').toUpperCase()));
  });
}

async function verifyAndroidBundle(options, dependencies = {}) {
  const artifactPath = resolve(options.artifactPath || '');
  if (!artifactPath.toLowerCase().endsWith('.aab')) {
    throw new Error('The Android store artifact must be an AAB.');
  }
  const artifact = statSync(artifactPath);
  if (!artifact.isFile() || artifact.size <= 0) throw new Error('Android App Bundle is empty or unavailable.');
  if (options.appIdentifier !== CANONICAL_ANDROID_PACKAGE) {
    throw new Error('EAS build metadata does not identify the canonical production package.');
  }
  if (!BUILD_ID_PATTERN.test(options.buildId || '')) throw new Error('EAS build ID is invalid.');
  if (!GIT_COMMIT_PATTERN.test(options.gitCommitHash || '')) throw new Error('Build Git commit hash is invalid.');

  const approvedFingerprints = options.approvedFingerprints instanceof Set
    ? options.approvedFingerprints
    : parseApprovedFingerprints(options.approvedFingerprints);
  const tools = dependencies.tools || resolveJavaTools(dependencies.environment);
  const execute = dependencies.runTool || runTool;
  parseBundleSignatureEntries(execute(tools.jar, ['tf', artifactPath]));
  const verificationOutput = execute(
    tools.jarsigner,
    ['-verify', '-strict', '-verbose', '-certs', artifactPath],
  );
  if (!/jar verified\./i.test(verificationOutput)) {
    throw new Error('Android App Bundle archive signature was not verified.');
  }
  const signingCertificateSha256 = parseBundleCertificate(
    execute(tools.keytool, ['-printcert', '-jarfile', artifactPath]),
  );
  if (!approvedFingerprints.has(signingCertificateSha256)) {
    throw new Error('Android App Bundle signer is not in the approved distribution fingerprint set.');
  }

  return Object.freeze({
    schema_version: 1,
    artifact_type: 'aab',
    artifact_file: basename(artifactPath),
    artifact_bytes: artifact.size,
    artifact_sha256: await sha256File(artifactPath),
    package_name: CANONICAL_ANDROID_PACKAGE,
    signing_certificate_sha256: signingCertificateSha256,
    eas_build_id: options.buildId.toLowerCase(),
    git_commit_hash: options.gitCommitHash.toLowerCase(),
  });
}

async function main() {
  const [artifactPath, receiptPath, buildId, gitCommitHash, appIdentifier] = process.argv.slice(2);
  if (!artifactPath || !receiptPath || !buildId || !gitCommitHash || !appIdentifier) {
    throw new Error(
      'Usage: verify-android-bundle <aab> <receipt.json> <eas-build-id> <git-commit-hash> <app-identifier>',
    );
  }
  const receipt = await verifyAndroidBundle({
    appIdentifier,
    approvedFingerprints: parseApprovedFingerprints(
      process.env.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
    ),
    artifactPath,
    buildId,
    gitCommitHash,
  });
  writeFileSync(resolve(receiptPath), `${JSON.stringify(receipt, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
    mode: 0o600,
  });
  process.stdout.write(
    `Verified ${receipt.package_name} production AAB; receipt SHA-256 ${receipt.artifact_sha256}.\n`,
  );
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

module.exports = {
  parseBundleCertificate,
  parseBundleSignatureEntries,
  resolveJavaTools,
  verifyAndroidBundle,
};
