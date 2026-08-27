import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { BUILD_CONFIG_INPUT_NAMES } = require('./android-build-config-fingerprint.js');
const {
  laneStagedArtifactPaths,
  parseCliArguments,
  resolveLaneStagedArtifactPath,
  stageAndroidApk,
  stagingManifestPath,
  verifyStagedAndroidApk,
} = require('./stage-android-apk.js');

const FINGERPRINT_HEX = 'A1'.repeat(32);
const APPROVED_FINGERPRINT = Array.from({ length: 32 }, () => 'A1').join(':');
const NATIVE_MANIFEST = Object.freeze({
  schema_version: 2,
  root: 'mobile/android',
  selection: 'test',
  exclusions: [],
  entries: [{ bytes: 1, path: 'android/app/build.gradle', sha256: 'D4'.repeat(32) }],
});
const NATIVE_SNAPSHOT = Object.freeze({
  file_count: 1,
  total_bytes: 1,
  sha256: createHash('sha256')
    .update(`${JSON.stringify(NATIVE_MANIFEST)}\n`)
    .digest('hex')
    .toUpperCase(),
  manifest: NATIVE_MANIFEST,
});
const BUILD_CONFIG_ENTRIES = Object.freeze(BUILD_CONFIG_INPUT_NAMES.map((name) => (
  Object.freeze(name === 'updates_enabled'
  ? {
      name,
      state: 'disabled',
      sha256: createHash('sha256').update(`${name}\0false`).digest('hex').toUpperCase(),
    }
  : { name, state: 'absent', sha256: null })
)));
const BUILD_CONFIG_MANIFEST = Object.freeze({
  schema_version: 2,
  scope: 'secret_safe_android_build_configuration',
  selection: 'test',
  entries: BUILD_CONFIG_ENTRIES,
});
const BUILD_CONFIG_FINGERPRINT = Object.freeze({
  schema_version: 2,
  evidence_level: 'configuration_observed_at_evidence_time_not_binary_attestation',
  input_count: BUILD_CONFIG_ENTRIES.length,
  sha256: createHash('sha256')
    .update(`${JSON.stringify(BUILD_CONFIG_MANIFEST)}\n`)
    .digest('hex')
    .toUpperCase(),
  manifest: BUILD_CONFIG_MANIFEST,
});
const RELEASE_POLICY = Object.freeze({
  approvedFingerprints: new Set([APPROVED_FINGERPRINT]),
  buildConfigFingerprint: BUILD_CONFIG_FINGERPRINT,
  expectedVersion: Object.freeze({ versionCode: 7, versionName: '1.0.0' }),
  nativeSnapshot: NATIVE_SNAPSHOT,
});

function signerOutput() {
  return [
    'Verifies',
    'Verified using v2 scheme (APK Signature Scheme v2): true',
    'Number of signers: 1',
    'V2 Signer: certificate DN: CN=Global Connect Travels Local Release',
    `V2 Signer: certificate SHA-256 digest: ${FINGERPRINT_HEX}`,
  ].join('\n');
}

function fixture(t, nativeAbi = 'arm64-v8a') {
  const directory = mkdtempSync(join(tmpdir(), 'gc-stage-apk-'));
  t.after(() => rmSync(directory, { force: true, recursive: true }));
  const sourceArtifactPath = join(directory, 'app-release.apk');
  const stagedArtifactPath = join(directory, 'staged', `app-release-${nativeAbi}.apk`);
  writeFileSync(sourceArtifactPath, 'signed-apk-fixture');
  const dependencies = {
    now: () => new Date('2026-08-27T18:00:00.000Z'),
    runTool: (tool, args) => {
      if (tool === 'apksigner') return signerOutput();
      if (tool === 'aapt2' && args[0] === 'dump') {
        return [
          "package: name='com.globalconnects.groupcompanion' versionCode='7' versionName='1.0.0'",
          `native-code: '${nativeAbi}'`,
        ].join('\n');
      }
      throw new Error('Unexpected staging verification tool invocation.');
    },
    tools: { aapt2: 'aapt2', apksigner: 'apksigner' },
  };
  return { dependencies, directory, sourceArtifactPath, stagedArtifactPath };
}

test('immediately creates and re-verifies a lane-specific APK and hash manifest', async (t) => {
  const {
    dependencies,
    sourceArtifactPath,
    stagedArtifactPath,
  } = fixture(t);
  const staged = await stageAndroidApk({
    ...RELEASE_POLICY,
    expectedAbi: 'arm64-v8a',
    sourceArtifactPath,
    stagedArtifactPath,
  }, dependencies);
  assert.equal(existsSync(stagedArtifactPath), true);
  assert.equal(existsSync(stagingManifestPath(stagedArtifactPath)), true);
  assert.equal(readFileSync(stagedArtifactPath, 'utf8'), 'signed-apk-fixture');
  assert.deepEqual(staged.manifest.native_abis, ['arm64-v8a']);
  assert.match(staged.manifest.artifact_sha256, /^[0-9A-F]{64}$/);
  assert.equal(staged.manifest.source_artifact_sha256, staged.manifest.artifact_sha256);
  assert.equal(staged.manifest.temporary_artifact_sha256, staged.manifest.artifact_sha256);
  assert.equal(staged.manifest.source_artifact_bytes, staged.manifest.artifact_bytes);
  assert.equal(staged.manifest.temporary_artifact_bytes, staged.manifest.artifact_bytes);
  assert.equal(staged.manifest.native_android_snapshot.sha256, NATIVE_SNAPSHOT.sha256);
  assert.equal(staged.manifest.build_config_fingerprint.sha256, BUILD_CONFIG_FINGERPRINT.sha256);

  const verified = await verifyStagedAndroidApk({
    ...RELEASE_POLICY,
    artifactPath: stagedArtifactPath,
    expectedAbi: 'arm64-v8a',
  }, dependencies);
  assert.equal(verified.manifest.artifact_sha256, staged.manifest.artifact_sha256);
});

test('durable lane evidence survives deletion of disposable Gradle build outputs', async (t) => {
  const { dependencies } = fixture(t, 'x86_64');
  const mobileRoot = mkdtempSync(join(tmpdir(), 'gc-durable-stage-apk-'));
  t.after(() => rmSync(mobileRoot, { force: true, recursive: true }));
  const buildRoot = join(mobileRoot, 'android', 'app', 'build');
  const sourceArtifactPath = join(
    buildRoot,
    'outputs',
    'apk',
    'release',
    'app-release.apk',
  );
  const paths = laneStagedArtifactPaths('x86_64', mobileRoot);
  mkdirSync(dirname(sourceArtifactPath), { recursive: true });
  mkdirSync(dirname(paths.legacy), { recursive: true });
  writeFileSync(sourceArtifactPath, 'signed-apk-fixture');
  writeFileSync(paths.legacy, 'previous-legacy-stage');
  assert.equal(resolveLaneStagedArtifactPath(paths.legacy, 'x86_64', {
    action: 'verify',
    mobileRoot,
  }), paths.legacy);
  assert.equal(resolveLaneStagedArtifactPath(paths.durable, 'x86_64', {
    action: 'verify',
    mobileRoot,
  }), paths.legacy);
  rmSync(paths.legacy);

  const stagedArtifactPath = resolveLaneStagedArtifactPath(paths.legacy, 'x86_64', {
    action: 'stage',
    mobileRoot,
  });
  assert.equal(stagedArtifactPath, paths.durable);
  await stageAndroidApk({
    ...RELEASE_POLICY,
    expectedAbi: 'x86_64',
    mobileRoot,
    sourceArtifactPath,
    stagedArtifactPath,
  }, dependencies);

  rmSync(buildRoot, { force: true, recursive: true });

  assert.equal(existsSync(paths.durable), true);
  assert.equal(existsSync(stagingManifestPath(paths.durable)), true);
  assert.equal(resolveLaneStagedArtifactPath(paths.legacy, 'x86_64', {
    action: 'verify',
    mobileRoot,
  }), paths.durable);
  const verified = await verifyStagedAndroidApk({
    ...RELEASE_POLICY,
    artifactPath: paths.durable,
    expectedAbi: 'x86_64',
  }, dependencies);
  assert.deepEqual(verified.manifest.native_abis, ['x86_64']);
});

test('fails closed when the staged APK changes after its immediate copy', async (t) => {
  const {
    dependencies,
    sourceArtifactPath,
    stagedArtifactPath,
  } = fixture(t);
  await stageAndroidApk({
    ...RELEASE_POLICY,
    expectedAbi: 'arm64-v8a',
    sourceArtifactPath,
    stagedArtifactPath,
  }, dependencies);
  writeFileSync(stagedArtifactPath, 'mutated-after-staging');
  await assert.rejects(
    () => verifyStagedAndroidApk({
      ...RELEASE_POLICY,
      artifactPath: stagedArtifactPath,
      expectedAbi: 'arm64-v8a',
    }, dependencies),
    /changed after its verified copy/,
  );
});

test('fails closed when generated Android native inputs drift after staging', async (t) => {
  const {
    dependencies,
    sourceArtifactPath,
    stagedArtifactPath,
  } = fixture(t);
  await stageAndroidApk({
    ...RELEASE_POLICY,
    expectedAbi: 'arm64-v8a',
    sourceArtifactPath,
    stagedArtifactPath,
  }, dependencies);
  const changedManifest = {
    ...NATIVE_MANIFEST,
    entries: [{ bytes: 1, path: 'android/app/build.gradle', sha256: 'E5'.repeat(32) }],
  };
  const changedSnapshot = {
    ...NATIVE_SNAPSHOT,
    sha256: createHash('sha256')
      .update(`${JSON.stringify(changedManifest)}\n`)
      .digest('hex')
      .toUpperCase(),
    manifest: changedManifest,
  };
  await assert.rejects(
    () => verifyStagedAndroidApk({
      ...RELEASE_POLICY,
      artifactPath: stagedArtifactPath,
      expectedAbi: 'arm64-v8a',
      nativeSnapshot: changedSnapshot,
    }, dependencies),
    /does not match the requested lane/,
  );
});

test('removes staged evidence when generated Android native inputs drift during staging', async (t) => {
  const {
    dependencies,
    sourceArtifactPath,
    stagedArtifactPath,
  } = fixture(t);
  const changedManifest = {
    ...NATIVE_MANIFEST,
    entries: [{ bytes: 1, path: 'android/app/build.gradle', sha256: 'F6'.repeat(32) }],
  };
  const changedSnapshot = {
    ...NATIVE_SNAPSHOT,
    sha256: createHash('sha256')
      .update(`${JSON.stringify(changedManifest)}\n`)
      .digest('hex')
      .toUpperCase(),
    manifest: changedManifest,
  };
  let snapshotCalls = 0;
  const nativeDependencies = {
    ...dependencies,
    nativeAndroidSourceManifest: () => {
      snapshotCalls += 1;
      return snapshotCalls === 1 ? NATIVE_SNAPSHOT : changedSnapshot;
    },
  };
  await assert.rejects(
    () => stageAndroidApk({
      approvedFingerprints: RELEASE_POLICY.approvedFingerprints,
      buildConfigFingerprint: BUILD_CONFIG_FINGERPRINT,
      expectedAbi: 'arm64-v8a',
      expectedVersion: RELEASE_POLICY.expectedVersion,
      sourceArtifactPath,
      stagedArtifactPath,
    }, nativeDependencies),
    /native sources changed during APK staging/,
  );
  assert.equal(existsSync(stagedArtifactPath), false);
  assert.equal(existsSync(stagingManifestPath(stagedArtifactPath)), false);
});

test('rejects ABI drift and refuses to replace an existing lane artifact', async (t) => {
  const {
    dependencies,
    sourceArtifactPath,
    stagedArtifactPath,
  } = fixture(t, 'x86_64');
  await assert.rejects(
    () => stageAndroidApk({
      ...RELEASE_POLICY,
      expectedAbi: 'arm64-v8a',
      sourceArtifactPath,
      stagedArtifactPath,
    }, dependencies),
    /must contain exactly arm64-v8a/,
  );

  mkdirSync(dirname(stagedArtifactPath), { recursive: true });
  writeFileSync(stagedArtifactPath, 'pre-existing-evidence');
  await assert.rejects(
    () => stageAndroidApk({
      ...RELEASE_POLICY,
      expectedAbi: 'x86_64',
      sourceArtifactPath,
      stagedArtifactPath,
    }, dependencies),
    /already exists/,
  );
  assert.equal(readFileSync(stagedArtifactPath, 'utf8'), 'pre-existing-evidence');
});

test('rejects an unapproved signer and source-version drift before staging', async (t) => {
  const {
    dependencies,
    sourceArtifactPath,
    stagedArtifactPath,
  } = fixture(t);
  await assert.rejects(
    () => stageAndroidApk({
      ...RELEASE_POLICY,
      approvedFingerprints: new Set([Array.from({ length: 32 }, () => 'B2').join(':')]),
      expectedAbi: 'arm64-v8a',
      sourceArtifactPath,
      stagedArtifactPath,
    }, dependencies),
    /not in the approved distribution fingerprint set/,
  );
  await assert.rejects(
    () => stageAndroidApk({
      ...RELEASE_POLICY,
      expectedAbi: 'arm64-v8a',
      expectedVersion: { versionCode: 8, versionName: '1.0.0' },
      sourceArtifactPath,
      stagedArtifactPath,
    }, dependencies),
    /must exactly match source version/,
  );
});

test('requires exact staging CLI argument counts', () => {
  const stageArgs = ['stage', 'source.apk', 'lane.apk', 'arm64-v8a'];
  const verifyArgs = ['verify', 'lane.apk', 'arm64-v8a'];
  assert.equal(parseCliArguments(stageArgs).action, 'stage');
  assert.equal(parseCliArguments(verifyArgs).action, 'verify');
  assert.throws(() => parseCliArguments([...stageArgs, 'surplus']), /Usage:/);
  assert.throws(() => parseCliArguments([...verifyArgs, 'surplus']), /Usage:/);
  assert.throws(() => parseCliArguments(['unknown']), /Usage:/);
});
