import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  normalizeFingerprint,
  parseApprovedFingerprints,
  parseApkSignerOutput,
  verifyAndroidArtifact,
} = require('./verify-android-artifact.js');

const APPROVED_HEX = 'A1'.repeat(32);
const APPROVED = normalizeFingerprint(APPROVED_HEX);
const BUILD_ID = '11111111-1111-4111-8111-111111111111';
const COMMIT = 'b'.repeat(40);

function signerOutput({
  certificate = APPROVED_HEX.toLowerCase(),
  debug = false,
  signerCount = 1,
  v2 = true,
} = {}) {
  return [
    'Verifies',
    `Verified using v2 scheme (APK Signature Scheme v2): ${String(v2)}`,
    `Number of signers: ${String(signerCount)}`,
    `V2 Signer: certificate DN: CN=${debug ? 'Android Debug' : 'Global Connect Travels'}, O=Example`,
    `V2 Signer: certificate SHA-256 digest: ${certificate}`,
  ].join('\n');
}

function fixture(t, overrides = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'gc-artifact-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const artifactPath = join(directory, 'production.apk');
  writeFileSync(artifactPath, 'signed-apk-fixture');
  const execute = (_tool, args) => (
    args[0] === 'verify'
      ? (overrides.signerOutput || signerOutput())
      : (overrides.packageOutput || "package: name='com.globalconnects.groupcompanion' versionCode='42'")
  );
  return {
    artifactPath,
    dependencies: {
      runTool: execute,
      tools: { apksigner: 'apksigner', aapt2: 'aapt2' },
    },
  };
}

test('verifies one approved non-debug signer and emits a bounded receipt', async (t) => {
  const { artifactPath, dependencies } = fixture(t);
  const receipt = await verifyAndroidArtifact({
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
  }, dependencies);
  assert.equal(receipt.package_name, 'com.globalconnects.groupcompanion');
  assert.equal(receipt.signing_certificate_sha256, APPROVED);
  assert.match(receipt.artifact_sha256, /^[0-9A-F]{64}$/);
  assert.deepEqual(Object.keys(receipt).sort(), [
    'artifact_bytes',
    'artifact_file',
    'artifact_sha256',
    'artifact_type',
    'eas_build_id',
    'git_commit_hash',
    'package_name',
    'schema_version',
    'signing_certificate_sha256',
  ]);
});

test('rejects debug, unsigned, multi-signer, and unapproved artifacts', async (t) => {
  assert.throws(() => parseApkSignerOutput(signerOutput({ debug: true })), /debug certificate/);
  assert.throws(() => parseApkSignerOutput(signerOutput({ v2: false })), /v2 or newer/);
  assert.throws(() => parseApkSignerOutput(signerOutput({ signerCount: 2 })), /exactly one signer/);

  const { artifactPath, dependencies } = fixture(t);
  await assert.rejects(() => verifyAndroidArtifact({
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(normalizeFingerprint('B2'.repeat(32))),
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
  }, dependencies), /not in the approved/);

  assert.throws(() => parseApprovedFingerprints(''), /is required/);
  assert.throws(
    () => parseApprovedFingerprints(Array.from({ length: 6 }, (_, index) => (
      normalizeFingerprint(index.toString(16).padStart(2, '0').repeat(32))
    )).join(',')),
    /limited to five/,
  );
});

test('rejects wrong package and malformed release provenance without echoing secrets', async (t) => {
  const { artifactPath, dependencies } = fixture(t, {
    packageOutput: "package: name='com.example.impostor' versionCode='42'",
  });
  await assert.rejects(() => verifyAndroidArtifact({
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
  }, dependencies), /package does not match/);
  await assert.rejects(() => verifyAndroidArtifact({
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    buildId: 'not-a-build',
    gitCommitHash: COMMIT,
  }, dependencies), /build ID is invalid/);
});
