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
import { basename, join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { BUILD_CONFIG_INPUT_NAMES } = require('./android-build-config-fingerprint.js');
const {
  REVIEWED_AAPT2_VERSION_OUTPUT,
  configuredToolVersions,
  createLocalAndroidSideloadReceipt,
  materializeLocalAndroidSideload,
  parseCliArguments,
  parseReviewedAapt2Version,
  sourceManifest,
  sourceState,
} = require('./package-local-android-sideload.js');

const FINGERPRINT_HEX = 'A1'.repeat(32);
const HEAD = 'b'.repeat(40);
const ARTIFACT_HASH = 'C3'.repeat(32);
const SNAPSHOT_HASH = 'D4'.repeat(32);
const APPROVED_FINGERPRINT = Array.from({ length: 32 }, () => 'A1').join(':');
const EXPECTED_VERSION = Object.freeze({ versionCode: 7, versionName: '1.0.0' });
const NATIVE_MANIFEST = Object.freeze({
  schema_version: 2,
  root: 'mobile/android',
  selection: 'test',
  exclusions: [],
  entries: [{ bytes: 1, path: 'android/app/build.gradle', sha256: 'A9'.repeat(32) }],
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

test('records the reviewed stderr-only aapt2 version without accepting tool drift', (t) => {
  const mobileRoot = mkdtempSync(join(tmpdir(), 'gc-tool-versions-'));
  t.after(() => rmSync(mobileRoot, { force: true, recursive: true }));
  const wrapperDirectory = join(mobileRoot, 'android', 'gradle', 'wrapper');
  const buildToolsDirectory = join(mobileRoot, 'sdk', 'build-tools', '37.0.0');
  mkdirSync(wrapperDirectory, { recursive: true });
  mkdirSync(buildToolsDirectory, { recursive: true });
  writeFileSync(join(mobileRoot, 'package.json'), JSON.stringify({
    dependencies: { expo: '~57.0.16', 'react-native': '0.86.2' },
  }));
  writeFileSync(join(wrapperDirectory, 'gradle-wrapper.properties'), [
    'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.3.1-bin.zip',
    'distributionSha256Sum=b266d5ff6b90eada6dc3b20cb090e3731302e553a27c5d3e4df1f0d76beaff06',
    '',
  ].join('\n'));
  const tools = {
    aapt2: join(buildToolsDirectory, process.platform === 'win32' ? 'aapt2.exe' : 'aapt2'),
    apksigner: join(
      buildToolsDirectory,
      process.platform === 'win32' ? 'apksigner.bat' : 'apksigner',
    ),
  };
  const versions = configuredToolVersions(mobileRoot, tools, (tool, args, options) => {
    if (tool === tools.apksigner) return '0.9\r\n';
    assert.deepEqual(args, ['version']);
    assert.deepEqual(options, { successOutput: 'exclusive-stdout-or-stderr' });
    return `${REVIEWED_AAPT2_VERSION_OUTPUT}\r\n`;
  });
  assert.equal(versions.android_build_tools, '37.0.0');
  assert.equal(versions.aapt2, REVIEWED_AAPT2_VERSION_OUTPUT);
  assert.throws(
    () => parseReviewedAapt2Version('Android Asset Packaging Tool (aapt) 2.21-unknown'),
    /does not match reviewed Android Build Tools 37\.0\.0/,
  );
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

function fixture(t, nativeAbi = 'x86_64', dependencyOverrides = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'gc-local-sideload-'));
  t.after(() => rmSync(directory, { force: true, recursive: true }));
  const artifactPath = join(directory, 'app-release.apk');
  const outputDirectory = join(directory, 'outputs');
  mkdirSync(outputDirectory);
  writeFileSync(artifactPath, 'signed-local-apk');
  const stageManifestPath = `${artifactPath}.stage.json`;
  const stageManifest = {
    schema_version: 2,
    evidence_level: 'local_build_staging_only',
    source_artifact_file: 'app-release.apk',
    source_artifact_bytes: 16,
    source_artifact_sha256: ARTIFACT_HASH,
    temporary_artifact_bytes: 16,
    temporary_artifact_sha256: ARTIFACT_HASH,
    artifact_file: basename(artifactPath),
    artifact_bytes: 16,
    artifact_sha256: ARTIFACT_HASH,
    package_name: 'com.globalconnects.groupcompanion',
    version_name: '1.0.0',
    version_code: 7,
    target_abi: nativeAbi,
    native_abis: [nativeAbi],
    signing_certificate_sha256: APPROVED_FINGERPRINT,
    native_android_snapshot: NATIVE_SNAPSHOT,
    build_config_fingerprint: BUILD_CONFIG_FINGERPRINT,
    staged_at_utc: '2026-08-27T18:00:00.000Z',
  };
  const stageManifestBytes = `${JSON.stringify(stageManifest, null, 2)}\n`;
  writeFileSync(stageManifestPath, stageManifestBytes);
  const stageEvidence = {
    manifest: stageManifest,
    manifestPath: stageManifestPath,
    manifestSha256: createHash('sha256').update(stageManifestBytes).digest('hex').toUpperCase(),
    nativeSnapshot: NATIVE_SNAPSHOT,
    buildConfigFingerprint: BUILD_CONFIG_FINGERPRINT,
  };
  const dependencies = {
    androidBuildConfigFingerprint: () => BUILD_CONFIG_FINGERPRINT,
    now: () => new Date('2026-08-27T18:00:00.000Z'),
    runTool: (tool, args) => {
      if (tool === 'apksigner') return signerOutput();
      if (tool === 'aapt2' && args[0] === 'dump') {
        return [
          "package: name='com.globalconnects.groupcompanion' versionCode='7' versionName='1.0.0'",
          `native-code: '${nativeAbi}'`,
        ].join('\n');
      }
      throw new Error('Unexpected local receipt verification tool invocation.');
    },
    sha256File: async () => ARTIFACT_HASH,
    sourceManifest: {
      file_count: 2,
      total_bytes: 42,
      sha256: SNAPSHOT_HASH,
      manifest: {
        schema_version: 1,
        root: 'mobile',
        selection: 'git tracked plus non-ignored untracked files',
        exclusions: ['outputs/'],
        entries: [
          { path: 'app.config.ts', bytes: 21, sha256: 'E5'.repeat(32) },
          { path: 'package.json', bytes: 21, sha256: 'F6'.repeat(32) },
        ],
      },
    },
    sourceState: {
      git_head: HEAD,
      repository_dirty: true,
      mobile_source_dirty: true,
    },
    tools: { aapt2: 'aapt2', apksigner: 'apksigner' },
    toolVersions: {
      node: 'v20.19.4',
      expo: '~57.0.16',
      react_native: '0.86.2',
      gradle_wrapper: 'gradle-9.0.0-bin.zip',
      android_build_tools: '36.0.0',
      apksigner: '0.9',
      aapt2: 'Android Asset Packaging Tool (aapt) 2.19',
    },
    ...dependencyOverrides,
  };
  return { artifactPath, dependencies, directory, outputDirectory, stageEvidence };
}

test('creates fail-honest dirty-worktree local sideload evidence without EAS claims', async (t) => {
  const { artifactPath, dependencies, stageEvidence } = fixture(t);
  const receipt = await createLocalAndroidSideloadReceipt({
    approvedFingerprints: new Set([APPROVED_FINGERPRINT]),
    artifactPath,
    buildTimestamp: '2020-01-01T00:00:00.000Z',
    expectedAbi: 'x86_64',
    expectedVersion: EXPECTED_VERSION,
    nativeSnapshot: NATIVE_SNAPSHOT,
    stageEvidence,
  }, dependencies);

  assert.equal(receipt.evidence_level, 'local_signed_sideload');
  assert.equal(receipt.release_eligible, false);
  assert.equal(receipt.source_dirty, true);
  assert.equal(receipt.mobile_source_dirty, true);
  assert.equal(receipt.git_head, HEAD);
  assert.equal(receipt.package_name, 'com.globalconnects.groupcompanion');
  assert.equal(receipt.version_name, '1.0.0');
  assert.equal(receipt.version_code, 7);
  assert.equal(receipt.expected_source_version_name, '1.0.0');
  assert.equal(receipt.expected_source_version_code, 7);
  assert.equal(receipt.target_abi, 'x86_64');
  assert.deepEqual(receipt.native_abis, ['x86_64']);
  assert.equal(receipt.artifact_sha256, ARTIFACT_HASH);
  assert.equal(receipt.staged_artifact_sha256, ARTIFACT_HASH);
  assert.equal(receipt.staging_manifest_sha256, stageEvidence.manifestSha256);
  assert.equal(receipt.native_android_snapshot.sha256, NATIVE_SNAPSHOT.sha256);
  assert.equal(receipt.build_config_fingerprint.sha256, BUILD_CONFIG_FINGERPRINT.sha256);
  assert.match(receipt.signing_assertion, /approved_distribution_fingerprint/);
  assert.equal(receipt.mobile_source_snapshot.sha256, SNAPSHOT_HASH);
  assert.equal('eas_build_id' in receipt, false);
  assert.equal(
    receipt.provenance_scope,
    'post_build_local_source_association_not_source_to_build_attestation',
  );
  assert.equal(receipt.source_snapshot_timing, 'captured_after_artifact_build');
  assert.match(receipt.canonical_artifact_file, /local-signed-sideload-x86_64/);
  assert.doesNotMatch(receipt.canonical_artifact_file, /production|eas/i);
});

test('materializes a post-build-associated canonical copy and adjacent exclusive receipt', async (t) => {
  const { artifactPath, dependencies, outputDirectory } = fixture(t, 'arm64-v8a');
  const result = await materializeLocalAndroidSideload({
    approvedFingerprints: new Set([APPROVED_FINGERPRINT]),
    artifactPath,
    buildTimestamp: '2020-01-01T00:00:00.000Z',
    expectedAbi: 'arm64-v8a',
    expectedVersion: EXPECTED_VERSION,
    nativeSnapshot: NATIVE_SNAPSHOT,
    outputDirectory,
  }, dependencies);

  assert.equal(existsSync(result.canonicalArtifactPath), true);
  assert.equal(existsSync(result.receiptPath), true);
  assert.equal(readFileSync(result.canonicalArtifactPath, 'utf8'), 'signed-local-apk');
  assert.deepEqual(
    JSON.parse(readFileSync(result.receiptPath, 'utf8')),
    result.receipt,
  );
  await assert.rejects(
    () => materializeLocalAndroidSideload({
      approvedFingerprints: new Set([APPROVED_FINGERPRINT]),
      artifactPath,
      buildTimestamp: '2020-01-01T00:00:00.000Z',
      expectedAbi: 'arm64-v8a',
      expectedVersion: EXPECTED_VERSION,
      nativeSnapshot: NATIVE_SNAPSHOT,
      outputDirectory,
    }, dependencies),
    /already exists/,
  );
});

test('refuses canonical packaging without the adjacent verified staging manifest', async (t) => {
  const { artifactPath, dependencies, outputDirectory } = fixture(t, 'x86_64');
  rmSync(`${artifactPath}.stage.json`);
  await assert.rejects(
    () => materializeLocalAndroidSideload({
      approvedFingerprints: new Set([APPROVED_FINGERPRINT]),
      artifactPath,
      buildTimestamp: '2020-01-01T00:00:00.000Z',
      expectedAbi: 'x86_64',
      expectedVersion: EXPECTED_VERSION,
      nativeSnapshot: NATIVE_SNAPSHOT,
      outputDirectory,
    }, dependencies),
    /staging manifest is unavailable/,
  );
});

test('mobile source snapshot hashing is deterministic and excludes generated or secret inputs', (t) => {
  const repository = mkdtempSync(join(tmpdir(), 'gc-source-manifest-'));
  t.after(() => rmSync(repository, { force: true, recursive: true }));
  mkdirSync(join(repository, 'mobile', 'outputs'), { recursive: true });
  writeFileSync(join(repository, 'mobile', 'app.config.ts'), 'app-config');
  writeFileSync(join(repository, 'mobile', '.env.local'), 'not-for-manifest');
  writeFileSync(join(repository, 'mobile', 'outputs', 'app.apk'), 'not-for-manifest');

  const listed = [
    'mobile/outputs/app.apk',
    'mobile/.env.local',
    'mobile/app.config.ts',
  ];
  const first = sourceManifest(repository, {
    runGit: () => `${listed.join('\0')}\0`,
  });
  const second = sourceManifest(repository, {
    runGit: () => `${[...listed].reverse().join('\0')}\0`,
  });
  assert.equal(first.sha256, second.sha256);
  assert.equal(first.file_count, 1);
  assert.deepEqual(first.manifest.entries.map((entry) => entry.path), ['app.config.ts']);
  assert.ok(first.manifest.exclusions.includes('outputs/'));
});

test('rejects an APK whose native ABI does not match the declared local lane', async (t) => {
  const { artifactPath, dependencies, stageEvidence } = fixture(t, 'x86_64');
  await assert.rejects(
    () => createLocalAndroidSideloadReceipt({
      approvedFingerprints: new Set([APPROVED_FINGERPRINT]),
      artifactPath,
      buildTimestamp: '2020-01-01T00:00:00.000Z',
      expectedAbi: 'arm64-v8a',
      expectedVersion: EXPECTED_VERSION,
      nativeSnapshot: NATIVE_SNAPSHOT,
      stageEvidence,
    }, dependencies),
    /must contain exactly arm64-v8a/,
  );
});

test('uses Git 2.9-compatible porcelain status arguments', () => {
  const calls = [];
  const state = sourceState('C:\\example-repository', {
    runGit: (_repoRoot, args) => {
      calls.push(args);
      if (args[0] === 'rev-parse') return `${HEAD}\n`;
      return args.includes('--') ? '' : ' M mobile/package.json\0';
    },
  });
  assert.equal(state.repository_dirty, true);
  assert.equal(state.mobile_source_dirty, false);
  const statusCalls = calls.filter((args) => args[0] === 'status');
  assert.equal(statusCalls.length, 2);
  assert.ok(statusCalls.every((args) => args.includes('--porcelain')));
  assert.ok(statusCalls.every((args) => !args.includes('--porcelain=v1')));
});

test('rejects an artifact that predates the declared build start', async (t) => {
  const { artifactPath, dependencies } = fixture(t);
  await assert.rejects(
    () => createLocalAndroidSideloadReceipt({
      artifactPath,
      buildTimestamp: '2099-01-01T00:00:00.000Z',
      expectedAbi: 'x86_64',
    }, dependencies),
    /predates the declared local build start/,
  );
});

test('removes a canonical copy when its final hash differs from verified staging', async (t) => {
  let hashCall = 0;
  const { artifactPath, dependencies, outputDirectory } = fixture(t, 'x86_64', {
    sha256File: async () => {
      hashCall += 1;
      return hashCall === 4 ? 'E7'.repeat(32) : ARTIFACT_HASH;
    },
  });
  await assert.rejects(
    () => materializeLocalAndroidSideload({
      approvedFingerprints: new Set([APPROVED_FINGERPRINT]),
      artifactPath,
      buildTimestamp: '2020-01-01T00:00:00.000Z',
      expectedAbi: 'x86_64',
      expectedVersion: EXPECTED_VERSION,
      nativeSnapshot: NATIVE_SNAPSHOT,
      outputDirectory,
    }, dependencies),
    /final canonical sideload copy does not match/,
  );
  assert.deepEqual(readdirSync(outputDirectory), []);
});

test('rejects missing and surplus packager CLI arguments', () => {
  const valid = ['artifact.apk', 'outputs', 'arm64-v8a', '2020-01-01T00:00:00.000Z'];
  assert.equal(parseCliArguments(valid).expectedAbi, 'arm64-v8a');
  assert.throws(() => parseCliArguments(valid.slice(0, -1)), /Usage:/);
  assert.throws(() => parseCliArguments([...valid, 'surplus']), /Usage:/);
});
