import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { normalizeFingerprint, parseApprovedFingerprints } = require('./verify-android-artifact.js');
const {
  parseBundleCertificate,
  parseBundleSignatureEntries,
  verifyAndroidBundle,
} = require('./verify-android-bundle.js');

const FINGERPRINT_HEX = 'C3'.repeat(32);
const FINGERPRINT = normalizeFingerprint(FINGERPRINT_HEX);

function fixture(t, override = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'gc-bundle-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const artifactPath = join(directory, 'production.aab');
  writeFileSync(artifactPath, 'signed-aab-fixture');
  const invocations = [];
  const runTool = (tool, args) => {
    invocations.push({ args, tool });
    if (tool === 'jar') return override.entries || 'META-INF/MANIFEST.MF\nMETA-INF/UPLOAD.RSA\nbase/manifest/AndroidManifest.xml\n';
    if (tool === 'jarsigner') return override.signature || 'jar verified.\n';
    return override.certificate || `Owner: CN=Global Connect Travels\nSHA256: ${FINGERPRINT}\n`;
  };
  return {
    artifactPath,
    dependencies: { runTool, tools: { jar: 'jar', jarsigner: 'jarsigner', keytool: 'keytool' } },
    invocations,
  };
}

test('verifies a single approved AAB signer in strict mode and emits checksum provenance', async (t) => {
  const { artifactPath, dependencies, invocations } = fixture(t);
  const receipt = await verifyAndroidBundle({
    appIdentifier: 'com.globalconnects.groupcompanion',
    approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
    artifactPath,
    buildId: '22222222-2222-4222-8222-222222222222',
    gitCommitHash: 'd'.repeat(40),
  }, dependencies);
  assert.equal(receipt.artifact_type, 'aab');
  assert.equal(receipt.signing_certificate_sha256, FINGERPRINT);
  assert.match(receipt.artifact_sha256, /^[0-9A-F]{64}$/);
  assert.deepEqual(
    invocations.find((invocation) => invocation.tool === 'jarsigner')?.args.slice(0, 4),
    ['-verify', '-strict', '-verbose', '-certs'],
  );
});

test('rejects multiple signer blocks, debug certificates, and invalid archive verification', async (t) => {
  assert.throws(
    () => parseBundleSignatureEntries('META-INF/ONE.RSA\nMETA-INF/TWO.EC\n'),
    /exactly one/,
  );
  assert.throws(
    () => parseBundleCertificate(`Owner: CN=Android Debug\nSHA256: ${FINGERPRINT}`),
    /debug certificate/,
  );
  const { artifactPath, dependencies } = fixture(t, { signature: 'jar is unsigned.' });
  await assert.rejects(() => verifyAndroidBundle({
    appIdentifier: 'com.globalconnects.groupcompanion',
    approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
    artifactPath,
    buildId: '22222222-2222-4222-8222-222222222222',
    gitCommitHash: 'd'.repeat(40),
  }, dependencies), /archive signature was not verified/);
});

test('rejects wrong package metadata and an unapproved distribution signer', async (t) => {
  const { artifactPath, dependencies } = fixture(t);
  await assert.rejects(() => verifyAndroidBundle({
    appIdentifier: 'com.example.wrong',
    approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
    artifactPath,
    buildId: '22222222-2222-4222-8222-222222222222',
    gitCommitHash: 'd'.repeat(40),
  }, dependencies), /canonical production package/);
  await assert.rejects(() => verifyAndroidBundle({
    appIdentifier: 'com.globalconnects.groupcompanion',
    approvedFingerprints: parseApprovedFingerprints(normalizeFingerprint('E4'.repeat(32))),
    artifactPath,
    buildId: '22222222-2222-4222-8222-222222222222',
    gitCommitHash: 'd'.repeat(40),
  }, dependencies), /approved distribution fingerprint/);
});
