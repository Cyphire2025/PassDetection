import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { normalizeFingerprint, parseApprovedFingerprints } = require('./verify-android-artifact.js');
const {
  BUNDLETOOL_SHA256,
  assertBundleArchiveVerification,
  inspectAndroidBundle,
  parseBundleCertificate,
  parseBundleManifestMetadata,
  parseBundleNativeAbiEvidence,
  parseBundleNativeAbis,
  parseBundleSignatureEntries,
  parseCliArguments,
  resolveJavaTools,
  verifyAndroidBundle,
} = require('./verify-android-bundle.js');

const FINGERPRINT_HEX = 'C3'.repeat(32);
const FINGERPRINT = normalizeFingerprint(FINGERPRINT_HEX);
const BUILD_ID = '22222222-2222-4222-8222-222222222222';
const COMMIT = 'd'.repeat(40);
const SOURCE_FINGERPRINT = 'e'.repeat(64);
const SOURCE_VERSION = Object.freeze({ versionCode: 42, versionName: '1.0.0' });

function fixture(t, override = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'gc-bundle-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const artifactPath = join(directory, 'production.aab');
  const bundletoolPath = join(directory, 'bundletool-all-1.18.3.jar');
  writeFileSync(artifactPath, 'signed-aab-fixture');
  writeFileSync(bundletoolPath, 'pinned-bundletool-fixture');
  const invocations = [];
  const runTool = (tool, args) => {
    invocations.push({ args, tool });
    if (tool === 'jar') return override.entries || [
      'META-INF/MANIFEST.MF',
      'META-INF/UPLOAD.RSA',
      'base/manifest/AndroidManifest.xml',
      'base/lib/arm64-v8a/libappmodules.so',
      'base/lib/armeabi-v7a/libappmodules.so',
      'base/lib/x86/libappmodules.so',
      'base/lib/x86_64/libappmodules.so',
    ].join('\n');
    if (tool === 'jarsigner') return override.signature || 'jar verified.\n';
    if (tool === 'java') {
      if (args.at(-1) === 'version') return override.bundletoolVersion || '1.18.3\n';
      const xpath = args.find((argument) => argument.startsWith('--xpath='));
      if (xpath === '--xpath=/manifest/@package') {
        return override.manifestPackage || 'com.globalconnects.groupcompanion\n';
      }
      if (xpath === '--xpath=/manifest/@android:versionCode') {
        return override.manifestVersionCode || '42\n';
      }
      if (xpath === '--xpath=/manifest/@android:versionName') {
        return override.manifestVersionName || '1.0.0\n';
      }
      throw new Error(`Unexpected bundletool invocation: ${args.join(' ')}`);
    }
    return override.certificate || `Owner: CN=Global Connect Travels\nSHA256: ${FINGERPRINT}\n`;
  };
  return {
    artifactPath,
    dependencies: {
      bundletoolSha256File: async () => BUNDLETOOL_SHA256,
      environment: { GC_ANDROID_BUNDLETOOL_JAR_PATH: bundletoolPath },
      resolveGitHead: () => COMMIT,
      runTool,
      tools: { java: 'java', jar: 'jar', jarsigner: 'jarsigner', keytool: 'keytool' },
    },
    invocations,
  };
}

test('verifies a single approved AAB signer and emits checksum provenance', async (t) => {
  const { artifactPath, dependencies, invocations } = fixture(t);
  const receipt = await verifyAndroidBundle({
    appBuildVersion: '42',
    appIdentifier: 'com.globalconnects.groupcompanion',
    appVersion: '1.0.0',
    approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
    artifactPath,
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
  }, dependencies);
  assert.equal(receipt.artifact_type, 'aab');
  assert.equal(receipt.package_evidence, 'bundletool_1.18.3_binary_manifest');
  assert.equal(receipt.signing_certificate_sha256, FINGERPRINT);
  assert.match(receipt.artifact_sha256, /^[0-9A-F]{64}$/);
  assert.deepEqual(receipt.native_abis, ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64']);
  assert.deepEqual(receipt.module_native_abis, {
    base: ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'],
  });
  assert.equal(receipt.version_name, '1.0.0');
  assert.equal(receipt.version_code, 42);
  assert.equal(receipt.schema_version, 3);
  assert.equal(receipt.source_fingerprint_hash, SOURCE_FINGERPRINT);
  assert.deepEqual(receipt.manifest_tool, {
    name: 'bundletool',
    sha256: BUNDLETOOL_SHA256,
    version: '1.18.3',
  });
  assert.match(
    receipt.canonical_artifact_file,
    /^global-connect-travels-android-play-bundle-d{12}-22222222-2222-4222-8222-222222222222\.aab$/,
  );
  assert.deepEqual(
    invocations.find((invocation) => invocation.tool === 'jarsigner')?.args.slice(0, 3),
    ['-verify', '-verbose', '-certs'],
  );
});

function runJavaFixtureTool(executable, args) {
  const result = spawnSync(executable, args, {
    encoding: 'utf8',
    maxBuffer: 16 * 1024 * 1024,
    shell: false,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Android self-signed bundle test tool failed with exit ${String(result.status)}.`);
  }
  return `${result.stdout || ''}\n${result.stderr || ''}`;
}

test('accepts a valid self-signed Android bundle and rejects tampering or unsigned entries', async (t) => {
  const directory = mkdtempSync(join(tmpdir(), 'gc-self-signed-bundle-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const payloadDirectory = join(directory, 'payload');
  for (const abi of ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64']) {
    const abiDirectory = join(payloadDirectory, 'base', 'lib', abi);
    mkdirSync(abiDirectory, { recursive: true });
    writeFileSync(join(abiDirectory, 'libfixture.so'), `fixture-${abi}`);
  }
  const artifactPath = join(directory, 'self-signed.aab');
  const keystorePath = join(directory, 'self-signed.jks');
  const tools = resolveJavaTools(process.env);
  runJavaFixtureTool(tools.keytool, [
    '-genkeypair',
    '-noprompt',
    '-alias',
    'release-audit',
    '-keyalg',
    'RSA',
    '-keystore',
    keystorePath,
    '-storepass',
    'auditpass',
    '-keypass',
    'auditpass',
    '-dname',
    'CN=Global Connect Travels Release Audit',
    '-validity',
    '3650',
  ]);
  runJavaFixtureTool(tools.jar, [
    '--create',
    '--file',
    artifactPath,
    '-C',
    payloadDirectory,
    '.',
  ]);
  runJavaFixtureTool(tools.jarsigner, [
    '-keystore',
    keystorePath,
    '-storepass',
    'auditpass',
    '-keypass',
    'auditpass',
    artifactPath,
    'release-audit',
  ]);
  const certificateOutput = runJavaFixtureTool(
    tools.keytool,
    ['-printcert', '-jarfile', artifactPath],
  );
  const approvedFingerprint = parseBundleCertificate(certificateOutput);
  const valid = await inspectAndroidBundle({
    approvedFingerprints: new Set([approvedFingerprint]),
    artifactPath,
    requireBinaryManifest: false,
  }, { tools });
  assert.equal(valid.signing_certificate_sha256, approvedFingerprint);
  assert.deepEqual(valid.native_abis, ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64']);
  await assert.rejects(
    () => inspectAndroidBundle({
      approvedFingerprints: new Set([normalizeFingerprint('A5'.repeat(32))]),
      artifactPath,
      requireBinaryManifest: false,
    }, { tools }),
    /approved distribution fingerprint/,
  );

  const tamperedArtifactPath = join(directory, 'tampered.aab');
  copyFileSync(artifactPath, tamperedArtifactPath);
  writeFileSync(
    join(payloadDirectory, 'base', 'lib', 'x86_64', 'libfixture.so'),
    'tampered-after-signing',
  );
  runJavaFixtureTool(tools.jar, [
    '--update',
    '--file',
    tamperedArtifactPath,
    '-C',
    payloadDirectory,
    'base/lib/x86_64/libfixture.so',
  ]);
  await assert.rejects(
    () => inspectAndroidBundle({
      approvedFingerprints: new Set([approvedFingerprint]),
      artifactPath: tamperedArtifactPath,
      requireBinaryManifest: false,
    }, { tools }),
    /verification tool failed/,
  );

  const unsignedArtifactPath = join(directory, 'unsigned-entry.aab');
  copyFileSync(artifactPath, unsignedArtifactPath);
  writeFileSync(join(payloadDirectory, 'unsigned-after-signing.txt'), 'unsigned');
  runJavaFixtureTool(tools.jar, [
    '--update',
    '--file',
    unsignedArtifactPath,
    '-C',
    payloadDirectory,
    'unsigned-after-signing.txt',
  ]);
  await assert.rejects(
    () => inspectAndroidBundle({
      approvedFingerprints: new Set([approvedFingerprint]),
      artifactPath: unsignedArtifactPath,
      requireBinaryManifest: false,
    }, { tools }),
    /unsigned archive entries/,
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
  assert.throws(
    () => assertBundleArchiveVerification(
      'jar verified.\nWarning: This jar contains unsigned entries which have not been integrity-checked.\n',
    ),
    /unsigned archive entries/,
  );
  const { artifactPath, dependencies } = fixture(t, { signature: 'jar is unsigned.' });
  await assert.rejects(() => verifyAndroidBundle({
    appBuildVersion: '42',
    appIdentifier: 'com.globalconnects.groupcompanion',
    appVersion: '1.0.0',
    approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
    artifactPath,
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
  }, dependencies), /archive signature was not verified/);
});

test('rejects wrong package metadata and an unapproved distribution signer', async (t) => {
  const { artifactPath, dependencies } = fixture(t);
  await assert.rejects(() => verifyAndroidBundle({
    appBuildVersion: '42',
    appIdentifier: 'com.example.wrong',
    appVersion: '1.0.0',
    approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
    artifactPath,
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
  }, dependencies), /canonical production package/);
  await assert.rejects(() => verifyAndroidBundle({
    appBuildVersion: '42',
    appIdentifier: 'com.globalconnects.groupcompanion',
    appVersion: '1.0.0',
    approvedFingerprints: parseApprovedFingerprints(normalizeFingerprint('E4'.repeat(32))),
    artifactPath,
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
  }, dependencies), /approved distribution fingerprint/);
});

test('requires every reviewed Play-delivered native ABI in the AAB', () => {
  const complete = [
    'base/lib/arm64-v8a/libapp.so',
    'base/lib/armeabi-v7a/libapp.so',
    'base/lib/x86/libapp.so',
    'base/lib/x86_64/libapp.so',
  ].join('\n');
  assert.deepEqual(
    parseBundleNativeAbis(complete),
    ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'],
  );
  assert.throws(
    () => parseBundleNativeAbis('base/lib/arm64-v8a/libapp.so'),
    /must contain exactly/,
  );
  assert.throws(
    () => parseBundleNativeAbis(`${complete}\nfeature_photos/lib/riscv64/libextra.so`),
    /module feature_photos must contain exactly/,
  );
  assert.throws(
    () => parseBundleNativeAbis(`${complete}\nfeature_photos/lib/arm64-v8a/libextra.so`),
    /module feature_photos must contain exactly/,
  );
});

test('normalizes listing whitespace without contaminating AAB module names', () => {
  const padded = [
    '',
    '  base/lib/arm64-v8a/libapp.so  ',
    '\tbase/lib/armeabi-v7a/libapp.so\t',
    'base/lib/x86/libapp.so\r',
    'base/lib/x86_64/libapp.so',
    '',
  ].join('\n');
  assert.deepEqual(parseBundleNativeAbiEvidence(padded), {
    moduleNativeAbis: {
      base: ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'],
    },
    nativeAbis: ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'],
  });
});

test('rejects unsafe paths and ambiguous AAB module names', () => {
  const complete = [
    'base/lib/arm64-v8a/libapp.so',
    'base/lib/armeabi-v7a/libapp.so',
    'base/lib/x86/libapp.so',
    'base/lib/x86_64/libapp.so',
  ].join('\n');
  assert.throws(
    () => parseBundleNativeAbiEvidence(complete.replaceAll('base/', '../')),
    /module name is invalid/,
  );
  assert.throws(
    () => parseBundleNativeAbiEvidence(complete.replaceAll('base/', 'base module/')),
    /module name is invalid/,
  );
  assert.throws(
    () => parseBundleNativeAbiEvidence(
      `${complete}\n${complete.replaceAll('base/', 'Base/')}`,
    ),
    /module names are ambiguous/,
  );
  assert.throws(
    () => parseBundleNativeAbiEvidence(
      `${complete}\nfeature/photos/lib/arm64-v8a/libextra.so`,
    ),
    /native library path is invalid/,
  );
});

test('rejects AAB EAS version-name drift from checked-out source', async (t) => {
  const { artifactPath, dependencies } = fixture(t);
  await assert.rejects(
    () => verifyAndroidBundle({
      appBuildVersion: '42',
      appIdentifier: 'com.globalconnects.groupcompanion',
      appVersion: '1.0.1',
      approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
      artifactPath,
      buildId: BUILD_ID,
      expectedSourceVersion: SOURCE_VERSION,
      gitCommitHash: COMMIT,
      sourceFingerprintHash: SOURCE_FINGERPRINT,
    }, dependencies),
    /does not match checked-out source/,
  );
  await assert.rejects(
    () => verifyAndroidBundle({
      appBuildVersion: '43',
      appIdentifier: 'com.globalconnects.groupcompanion',
      appVersion: '1.0.0',
      approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
      artifactPath,
      buildId: BUILD_ID,
      expectedSourceVersion: SOURCE_VERSION,
      gitCommitHash: COMMIT,
      sourceFingerprintHash: SOURCE_FINGERPRINT,
    }, dependencies),
    /does not match checked-out source/,
  );
});

test('rejects missing and surplus bundle-verifier CLI arguments', () => {
  const valid = [
    'artifact.aab',
    'receipt.json',
    BUILD_ID,
    COMMIT,
    SOURCE_FINGERPRINT,
    'com.globalconnects.groupcompanion',
    '1.0.0',
    '42',
  ];
  assert.equal(parseCliArguments(valid).appIdentifier, 'com.globalconnects.groupcompanion');
  assert.throws(() => parseCliArguments(valid.slice(0, -1)), /Usage:/);
  assert.throws(() => parseCliArguments([...valid, 'surplus']), /Usage:/);
});

test('requires pinned bundletool binary metadata and exact checked-out provenance', async (t) => {
  assert.throws(
    () => parseBundleManifestMetadata({
      packageName: 'not-a-package',
      versionCode: '42',
      versionName: '1.0.0',
    }),
    /package name is invalid/,
  );
  const { artifactPath, dependencies } = fixture(t, {
    manifestPackage: 'com.example.impostor\n',
  });
  const options = {
    appBuildVersion: '42',
    appIdentifier: 'com.globalconnects.groupcompanion',
    appVersion: '1.0.0',
    approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
    artifactPath,
    buildId: BUILD_ID,
    expectedSourceVersion: SOURCE_VERSION,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
  };
  await assert.rejects(
    () => verifyAndroidBundle(options, dependencies),
    /binary package does not match/,
  );
  await assert.rejects(
    () => verifyAndroidBundle(options, {
      ...dependencies,
      bundletoolSha256File: async () => '0'.repeat(64),
    }),
    /bundletool 1\.18\.3 checksum is invalid/,
  );
  await assert.rejects(
    () => verifyAndroidBundle(options, {
      ...dependencies,
      resolveGitHead: () => 'a'.repeat(40),
    }),
    /HEAD does not match/,
  );
  await assert.rejects(
    () => verifyAndroidBundle(options, {
      ...dependencies,
      environment: {},
    }),
    /required for release-eligible AAB verification/,
  );
  const fallback = await inspectAndroidBundle({
    approvedFingerprints: parseApprovedFingerprints(FINGERPRINT),
    artifactPath,
    requireBinaryManifest: false,
  }, {
    ...dependencies,
    environment: {},
  });
  assert.equal(fallback.manifest_metadata, null);
  assert.equal(fallback.manifest_tool, null);
});
