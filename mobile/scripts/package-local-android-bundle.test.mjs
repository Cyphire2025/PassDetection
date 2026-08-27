import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { BUILD_CONFIG_INPUT_NAMES } = require('./android-build-config-fingerprint.js');
const {
  materializeLocalAndroidBundle,
  parseCliArguments,
} = require('./package-local-android-bundle.js');

const HASH = 'A1'.repeat(32);
const FINGERPRINT = 'B2:'.repeat(31) + 'B2';
const HEAD = 'c'.repeat(40);
const SNAPSHOT = 'D3'.repeat(32);
const NATIVE_MANIFEST = Object.freeze({
  schema_version: 2,
  root: 'mobile/android',
  selection: 'test',
  exclusions: [],
  entries: [{ bytes: 1, path: 'android/app/build.gradle', sha256: 'F6'.repeat(32) }],
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

function fixture(t, overrides = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'gc-local-aab-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const artifactPath = join(directory, 'app-release.aab');
  const outputDirectory = join(directory, 'outputs');
  mkdirSync(outputDirectory);
  writeFileSync(artifactPath, 'signed-aab-fixture');
  const details = {
    artifact_bytes: 18,
    artifact_sha256: HASH,
    module_native_abis: {
      base: ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'],
    },
    native_abis: ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'],
    signing_certificate_sha256: FINGERPRINT,
  };
  const dependencies = {
    androidBuildConfigFingerprint: () => BUILD_CONFIG_FINGERPRINT,
    inspectAndroidBundle: async () => details,
    loadReviewedGradleWrapper: () => ({
      distributionSha256: 'B6'.repeat(32).toLowerCase(),
      distributionUrl: 'https://services.gradle.org/distributions/gradle-9.3.1-bin.zip',
      version: '9.3.1',
    }),
    now: () => new Date('2026-08-28T01:00:00.000Z'),
    sha256File: async () => HASH,
    sourceManifest: {
      file_count: 1,
      manifest: { entries: [], root: 'mobile', schema_version: 1 },
      sha256: SNAPSHOT,
      total_bytes: 1,
    },
    sourceState: {
      git_head: HEAD,
      mobile_source_dirty: true,
      repository_dirty: true,
    },
    ...overrides,
  };
  return { artifactPath, dependencies, details, outputDirectory };
}

test('creates an honest local-only canonical AAB and adjacent receipt', async (t) => {
  const { artifactPath, dependencies, outputDirectory } = fixture(t);
  const result = await materializeLocalAndroidBundle({
    approvedFingerprints: new Set([FINGERPRINT]),
    artifactPath,
    buildTimestamp: '2020-01-01T00:00:00.000Z',
    expectedVersion: { versionCode: 3, versionName: '1.0.2' },
    nativeSnapshot: NATIVE_SNAPSHOT,
    outputDirectory,
  }, dependencies);
  assert.equal(existsSync(result.canonicalArtifactPath), true);
  assert.equal(existsSync(result.receiptPath), true);
  assert.equal(result.receipt.release_eligible, false);
  assert.equal(result.receipt.schema_version, 2);
  assert.equal(result.receipt.artifact_sha256, HASH);
  assert.equal(result.receipt.expected_source_version_name, '1.0.2');
  assert.equal(result.receipt.expected_source_version_code, 3);
  assert.equal(result.receipt.expected_package_name, 'com.globalconnects.groupcompanion');
  assert.equal('package_name' in result.receipt, false);
  assert.match(result.receipt.package_evidence, /not_archive_manifest/);
  assert.match(result.receipt.version_evidence, /not_archive_derived/);
  assert.equal(result.receipt.native_android_snapshot.sha256, NATIVE_SNAPSHOT.sha256);
  assert.equal(result.receipt.build_config_fingerprint.sha256, BUILD_CONFIG_FINGERPRINT.sha256);
  assert.equal(result.receipt.tool_versions.gradle_wrapper, 'gradle-9.3.1-bin.zip');
  assert.equal(result.receipt.tool_versions.gradle_distribution_sha256, 'b6'.repeat(32));
  assert.deepEqual(JSON.parse(readFileSync(result.receiptPath, 'utf8')), result.receipt);
});

test('records binary AAB identity only when the pinned manifest parser proves it', async (t) => {
  const { artifactPath, dependencies, details, outputDirectory } = fixture(t);
  const inspectionOptions = [];
  dependencies.inspectAndroidBundle = async (options) => {
    inspectionOptions.push(options);
    return {
      ...details,
      manifest_metadata: {
        packageName: 'com.globalconnects.groupcompanion',
        versionCode: 3,
        versionName: '1.0.2',
      },
      manifest_tool: {
        name: 'bundletool',
        sha256: 'C4'.repeat(32),
        version: '1.18.3',
      },
    };
  };
  const result = await materializeLocalAndroidBundle({
    approvedFingerprints: new Set([FINGERPRINT]),
    artifactPath,
    buildTimestamp: '2020-01-01T00:00:00.000Z',
    expectedVersion: { versionCode: 3, versionName: '1.0.2' },
    nativeSnapshot: NATIVE_SNAPSHOT,
    outputDirectory,
  }, dependencies);
  assert.equal(result.receipt.release_eligible, false);
  assert.equal(result.receipt.package_name, 'com.globalconnects.groupcompanion');
  assert.equal(result.receipt.version_name, '1.0.2');
  assert.equal(result.receipt.version_code, 3);
  assert.match(result.receipt.package_evidence, /bundletool_1\.18\.3_binary_manifest/);
  assert.ok(inspectionOptions.every((options) => options.requireBinaryManifest === false));
});

test('removes a canonical AAB if final verification differs', async (t) => {
  let inspections = 0;
  const { artifactPath, dependencies, outputDirectory } = fixture(t, {
    inspectAndroidBundle: async () => {
      inspections += 1;
      return {
        artifact_bytes: 18,
        artifact_sha256: inspections === 3 ? 'E4'.repeat(32) : HASH,
        module_native_abis: { base: ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'] },
        native_abis: ['arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'],
        signing_certificate_sha256: FINGERPRINT,
      };
    },
  });
  await assert.rejects(
    () => materializeLocalAndroidBundle({
      approvedFingerprints: new Set([FINGERPRINT]),
      artifactPath,
      buildTimestamp: '2020-01-01T00:00:00.000Z',
      expectedVersion: { versionCode: 3, versionName: '1.0.2' },
      nativeSnapshot: NATIVE_SNAPSHOT,
      outputDirectory,
    }, dependencies),
    /changed during local canonical packaging/,
  );
  assert.deepEqual(readdirSync(outputDirectory), []);
});

test('removes local AAB evidence when generated native inputs drift during packaging', async (t) => {
  let snapshotCalls = 0;
  const changedManifest = {
    ...NATIVE_MANIFEST,
    entries: [{ bytes: 1, path: 'android/app/build.gradle', sha256: 'F7'.repeat(32) }],
  };
  const changedSnapshot = {
    ...NATIVE_SNAPSHOT,
    sha256: createHash('sha256')
      .update(`${JSON.stringify(changedManifest)}\n`)
      .digest('hex')
      .toUpperCase(),
    manifest: changedManifest,
  };
  const { artifactPath, dependencies, outputDirectory } = fixture(t, {
    nativeAndroidSourceManifest: () => {
      snapshotCalls += 1;
      return snapshotCalls === 1
        ? NATIVE_SNAPSHOT
        : changedSnapshot;
    },
  });
  await assert.rejects(
    () => materializeLocalAndroidBundle({
      approvedFingerprints: new Set([FINGERPRINT]),
      artifactPath,
      buildTimestamp: '2020-01-01T00:00:00.000Z',
      expectedVersion: { versionCode: 3, versionName: '1.0.2' },
      outputDirectory,
    }, dependencies),
    /native sources changed/,
  );
  assert.deepEqual(readdirSync(outputDirectory), []);
});

test('requires exact local AAB packager arguments', () => {
  const valid = ['app.aab', 'outputs', '2026-08-28T00:00:00.000Z'];
  assert.equal(parseCliArguments(valid).artifactPath, 'app.aab');
  assert.throws(() => parseCliArguments(valid.slice(0, -1)), /Usage:/);
  assert.throws(() => parseCliArguments([...valid, 'surplus']), /Usage:/);
});
