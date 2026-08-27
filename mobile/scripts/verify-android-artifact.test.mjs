import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import {
  appendFileSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  REVIEWED_ANDROID_BUILD_TOOLS_VERSION,
  normalizeFingerprint,
  parseApprovedFingerprints,
  parseApkNativeAbis,
  parseApkSignerOutput,
  parseCliArguments,
  resolveAndroidBuildTools,
  runTool,
  verifyAndroidArtifact,
} = require('./verify-android-artifact.js');

const APPROVED_HEX = 'A1'.repeat(32);
const APPROVED = normalizeFingerprint(APPROVED_HEX);
const BUILD_ID = '11111111-1111-4111-8111-111111111111';
const COMMIT = 'b'.repeat(40);
const SOURCE_FINGERPRINT = 'f'.repeat(64);
const SOURCE_VERSION = Object.freeze({ versionCode: 42, versionName: '1.0.0' });

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
      : (overrides.packageOutput || [
        "package: name='com.globalconnects.groupcompanion' versionCode='42' versionName='1.0.0'",
        "native-code: 'arm64-v8a'",
      ].join('\n'))
  );
  return {
    artifactPath,
    dependencies: {
      resolveGitHead: () => COMMIT,
      runTool: execute,
      tools: { apksigner: 'apksigner', aapt2: 'aapt2' },
    },
  };
}

function createBuildTools(directory, version) {
  const buildToolsDirectory = join(directory, 'build-tools', version);
  mkdirSync(buildToolsDirectory, { recursive: true });
  const apksigner = join(
    buildToolsDirectory,
    process.platform === 'win32' ? 'apksigner.bat' : 'apksigner',
  );
  const aapt2 = join(
    buildToolsDirectory,
    process.platform === 'win32' ? 'aapt2.exe' : 'aapt2',
  );
  writeFileSync(apksigner, 'reviewed-apksigner');
  writeFileSync(aapt2, 'reviewed-aapt2');
  return { aapt2, apksigner };
}

test('resolves only reviewed Android Build Tools 37.0.0', (t) => {
  const sdkRoot = mkdtempSync(join(tmpdir(), 'gc-reviewed-build-tools-'));
  t.after(() => rmSync(sdkRoot, { recursive: true, force: true }));
  const reviewed = createBuildTools(sdkRoot, REVIEWED_ANDROID_BUILD_TOOLS_VERSION);
  createBuildTools(sdkRoot, '99.0.0');
  const resolved = resolveAndroidBuildTools({ ANDROID_HOME: sdkRoot });
  assert.equal(resolved.version, '37.0.0');
  assert.equal(resolved.apksigner, reviewed.apksigner);
  assert.equal(resolved.aapt2, reviewed.aapt2);

  assert.deepEqual(
    resolveAndroidBuildTools({
      GC_AAPT2_PATH: reviewed.aapt2,
      GC_APKSIGNER_PATH: reviewed.apksigner,
    }),
    { ...reviewed, version: '37.0.0' },
  );
});

test('fails closed instead of selecting a newer or incomplete Build Tools directory', (t) => {
  const sdkRoot = mkdtempSync(join(tmpdir(), 'gc-unreviewed-build-tools-'));
  t.after(() => rmSync(sdkRoot, { recursive: true, force: true }));
  const newer = createBuildTools(sdkRoot, '99.0.0');
  assert.throws(
    () => resolveAndroidBuildTools({ ANDROID_HOME: sdkRoot }),
    /reviewed Android Build Tools 37\.0\.0.*apksigner/i,
  );
  assert.throws(
    () => resolveAndroidBuildTools({
      GC_AAPT2_PATH: newer.aapt2,
      GC_APKSIGNER_PATH: newer.apksigner,
    }),
    /both tools from reviewed Android Build Tools 37\.0\.0/i,
  );
  assert.throws(
    () => resolveAndroidBuildTools({ GC_APKSIGNER_PATH: newer.apksigner }),
    /must both reference reviewed Android Build Tools 37\.0\.0/i,
  );
});

test('captures an explicitly requested stderr-only successful tool version safely', () => {
  const versionOutput = 'Android Asset Packaging Tool (aapt) 2.20-15087165\r\n';
  assert.equal(
    runTool(
      process.execPath,
      ['-e', `process.stderr.write(${JSON.stringify(versionOutput)})`],
      { successOutput: 'exclusive-stdout-or-stderr' },
    ),
    versionOutput,
  );
  assert.throws(
    () => runTool(
      process.execPath,
      ['-e', 'process.stdout.write("version"); process.stderr.write("warning")'],
      { successOutput: 'exclusive-stdout-or-stderr' },
    ),
    /ambiguous successful output/,
  );
});

test('verifies one approved non-debug signer and emits a bounded receipt', async (t) => {
  const { artifactPath, dependencies } = fixture(t);
  const receipt = await verifyAndroidArtifact({
    appBuildVersion: '42',
    appVersion: '1.0.0',
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
  }, dependencies);
  assert.equal(receipt.package_name, 'com.globalconnects.groupcompanion');
  assert.equal(receipt.signing_certificate_sha256, APPROVED);
  assert.match(receipt.artifact_sha256, /^[0-9A-F]{64}$/);
  assert.deepEqual(Object.keys(receipt).sort(), [
    'artifact_bytes',
    'artifact_file',
    'artifact_sha256',
    'artifact_type',
    'canonical_artifact_file',
    'eas_build_id',
    'git_commit_hash',
    'native_abis',
    'package_name',
    'schema_version',
    'signing_certificate_sha256',
    'source_fingerprint_hash',
    'source_version_code',
    'source_version_name',
    'version_code',
    'version_evidence',
    'version_name',
  ]);
  assert.deepEqual(receipt.native_abis, ['arm64-v8a']);
  assert.equal(receipt.schema_version, 3);
  assert.equal(receipt.source_fingerprint_hash, SOURCE_FINGERPRINT);
  assert.match(
    receipt.canonical_artifact_file,
    /^global-connect-travels-android-arm64-v8a-sideload-b{12}-11111111-1111-4111-8111-111111111111\.apk$/,
  );
});

test('rejects debug, unsigned, multi-signer, and unapproved artifacts', async (t) => {
  assert.throws(() => parseApkSignerOutput(signerOutput({ debug: true })), /debug certificate/);
  assert.throws(() => parseApkSignerOutput(signerOutput({ v2: false })), /v2 or newer/);
  assert.throws(() => parseApkSignerOutput(signerOutput({ signerCount: 2 })), /exactly one signer/);

  const { artifactPath, dependencies } = fixture(t);
  await assert.rejects(() => verifyAndroidArtifact({
    appBuildVersion: '42',
    appVersion: '1.0.0',
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(normalizeFingerprint('B2'.repeat(32))),
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
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
    packageOutput: "package: name='com.example.impostor' versionCode='42' versionName='1.0.0'\nnative-code: 'arm64-v8a'",
  });
  await assert.rejects(() => verifyAndroidArtifact({
    appBuildVersion: '42',
    appVersion: '1.0.0',
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    buildId: BUILD_ID,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
  }, dependencies), /package does not match/);
  await assert.rejects(() => verifyAndroidArtifact({
    appBuildVersion: '42',
    appVersion: '1.0.0',
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    buildId: 'not-a-build',
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
  }, dependencies), /build ID is invalid/);
});

test('requires an ARM64-only installable production artifact', () => {
  assert.deepEqual(parseApkNativeAbis("native-code: 'arm64-v8a'"), ['arm64-v8a']);
  assert.throws(
    () => parseApkNativeAbis("native-code: 'arm64-v8a' 'x86_64'"),
    /must contain exactly arm64-v8a/,
  );
  assert.throws(() => parseApkNativeAbis('package: name=example'), /does not declare/);
});

test('supports a separately bound x86_64 emulator verification artifact', async (t) => {
  const { artifactPath, dependencies } = fixture(t, {
    packageOutput: [
      "package: name='com.globalconnects.groupcompanion' versionCode='42' versionName='1.0.0'",
      "native-code: 'x86_64'",
    ].join('\n'),
  });
  const receipt = await verifyAndroidArtifact({
    appBuildVersion: '42',
    appVersion: '1.0.0',
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    buildId: BUILD_ID,
    expectedAbi: 'x86_64',
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
    expectedSourceVersion: SOURCE_VERSION,
  }, dependencies);
  assert.deepEqual(receipt.native_abis, ['x86_64']);
  assert.match(receipt.canonical_artifact_file, /android-x86_64-sideload/);
});

test('rejects APK version drift from source or EAS build metadata', async (t) => {
  const { artifactPath, dependencies } = fixture(t);
  const baseline = {
    appBuildVersion: '42',
    appVersion: '1.0.0',
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    artifactPath,
    buildId: BUILD_ID,
    expectedSourceVersion: SOURCE_VERSION,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
  };
  await assert.rejects(
    () => verifyAndroidArtifact({ ...baseline, appBuildVersion: '43' }, dependencies),
    /version does not match/,
  );
  await assert.rejects(
    () => verifyAndroidArtifact({
      ...baseline,
      expectedSourceVersion: { versionCode: 42, versionName: '1.0.1' },
    }, dependencies),
    /version does not match/,
  );
});

test('rejects missing and surplus verifier CLI arguments', () => {
  const valid = [
    'artifact.apk',
    'receipt.json',
    BUILD_ID,
    COMMIT,
    SOURCE_FINGERPRINT,
    'x86_64',
    '1.0.0',
    '42',
  ];
  assert.equal(parseCliArguments(valid).expectedAbi, 'x86_64');
  assert.throws(() => parseCliArguments(valid.slice(0, -1)), /Usage:/);
  assert.throws(() => parseCliArguments([...valid, 'arm64-v8a']), /Usage:/);
});

test('binds verification to checked-out HEAD and rejects a mutated verifier snapshot', async (t) => {
  const { artifactPath, dependencies } = fixture(t);
  const options = {
    appBuildVersion: '42',
    appVersion: '1.0.0',
    artifactPath,
    approvedFingerprints: parseApprovedFingerprints(APPROVED),
    buildId: BUILD_ID,
    expectedSourceVersion: SOURCE_VERSION,
    gitCommitHash: COMMIT,
    sourceFingerprintHash: SOURCE_FINGERPRINT,
  };
  await assert.rejects(
    () => verifyAndroidArtifact(options, {
      ...dependencies,
      resolveGitHead: () => 'c'.repeat(40),
    }),
    /HEAD does not match/,
  );

  let mutated = false;
  await assert.rejects(
    () => verifyAndroidArtifact(options, {
      ...dependencies,
      runTool: (tool, args) => {
        const output = dependencies.runTool(tool, args);
        if (!mutated) {
          appendFileSync(args.at(-1), '-tampered');
          mutated = true;
        }
        return output;
      },
    }),
    /snapshot changed during verification/,
  );
});
