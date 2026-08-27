import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const plugin = require('../plugins/with-android-release-signing');

const GENERATED_GRADLE_FIXTURE = `apply plugin: "com.android.application"

android {
    namespace 'com.example.app'
    signingConfigs {
        debug {
            storeFile file('debug.keystore')
            storePassword 'android'
            keyAlias 'androiddebugkey'
            keyPassword 'android'
        }
    }
    buildTypes {
        debug {
            signingConfig signingConfigs.debug
        }
        release {
            // Expo's generated release fallback must not survive.
            signingConfig signingConfigs.debug
            minifyEnabled true
        }
    }
}
`;

test('release signing transform is idempotent and removes the debug fallback', () => {
  const patched = plugin.patchAppBuildGradle(GENERATED_GRADLE_FIXTURE);

  assert.equal(plugin.patchAppBuildGradle(patched), patched);
  assert.match(patched, /System\.getenv\(variableName\)/);
  assert.match(patched, /signingConfig signingConfigs\.release/);
  assert.match(patched, /signingConfig null/);
  assert.match(patched, /taskName\.startsWith\('assemble'\)/);
  assert.match(patched, /taskName\.startsWith\('bundle'\)/);
  assert.match(patched, /Android release signing is required/);

  const debugBindings = patched.match(/signingConfig signingConfigs\.debug/g) ?? [];
  assert.equal(debugBindings.length, 1, 'only the debug build type may use the debug key');
});

test('credentials remain Gradle environment references and are never captured by the transform', () => {
  const sentinels = [
    'DO_NOT_CAPTURE_KEYSTORE_PATH',
    'DO_NOT_CAPTURE_STORE_PASSWORD',
    'DO_NOT_CAPTURE_ALIAS',
    'DO_NOT_CAPTURE_KEY_PASSWORD',
  ];
  const names = [
    'GC_ANDROID_KEYSTORE_FILE',
    'GC_ANDROID_KEYSTORE_PASSWORD',
    'GC_ANDROID_KEY_ALIAS',
    'GC_ANDROID_KEY_PASSWORD',
  ];
  const previous = new Map(names.map((name) => [name, process.env[name]]));
  names.forEach((name, index) => { process.env[name] = sentinels[index]; });

  try {
    const patched = plugin.patchAppBuildGradle(GENERATED_GRADLE_FIXTURE);
    for (const name of names) assert.match(patched, new RegExp(name));
    for (const sentinel of sentinels) assert.doesNotMatch(patched, new RegExp(sentinel));
    assert.match(patched, /gcReleaseSigningPresentCount > 0/);
    assert.match(patched, /partially configured/);
    assert.doesNotMatch(patched, /println|logger\.|System\.out/);
  } finally {
    for (const [name, value] of previous) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  }
});

test('Android release CI provisions only runner-local verification signing', () => {
  const workflow = readFileSync(
    new URL('../../.github/workflows/mobile-ci.yml', import.meta.url),
    'utf8',
  );
  const androidJobStart = workflow.indexOf('  android-release:');
  const iosJobStart = workflow.indexOf('  ios-compile:', androidJobStart);
  assert.notEqual(androidJobStart, -1, 'Android release CI job must exist');
  assert.notEqual(iosJobStart, -1, 'iOS release CI job must follow Android');
  const androidJob = workflow.slice(androidJobStart, iosJobStart);
  const signingStep = androidJob.indexOf(
    '- name: Create ephemeral Android verification signing',
  );
  const dependencyInstallStep = androidJob.indexOf('- run: npm ci --include=dev');
  const firebaseFixtureStep = androidJob.indexOf(
    '- name: Create non-production Firebase compile fixture',
  );
  const prebuildStep = androidJob.indexOf('- name: Generate a clean Android project');
  const releaseBuildStep = androidJob.indexOf(
    '- name: Build release variants (verification signing only)',
  );
  const sizeGateStep = androidJob.indexOf(
    '- name: Enforce reviewed APK and AAB size budgets',
  );

  assert.ok(
    signingStep >= 0
      && signingStep < dependencyInstallStep
      && dependencyInstallStep < firebaseFixtureStep
      && firebaseFixtureStep < prebuildStep,
  );
  assert.ok(prebuildStep < releaseBuildStep && releaseBuildStep < sizeGateStep);
  const jobEnvironment = androidJob.slice(0, signingStep);
  const signingBlock = androidJob.slice(signingStep, dependencyInstallStep);
  const firebaseFixtureBlock = androidJob.slice(firebaseFixtureStep, prebuildStep);
  const buildBlock = androidJob.slice(releaseBuildStep, sizeGateStep);

  assert.match(jobEnvironment, /NODE_ENV: production/);
  assert.match(signingBlock, /signing_dir="\$\{RUNNER_TEMP\}\//);
  assert.match(signingBlock, /randomBytes\(32\)/);
  assert.match(signingBlock, /echo "::add-mask::\$\{signing_password\}"/);
  assert.match(signingBlock, /keytool -genkeypair/);
  assert.match(signingBlock, /keytool -exportcert/);
  assert.match(signingBlock, /createHash\('sha256'\)/);
  assert.match(signingBlock, /readFileSync\(process\.argv\[1\]\)/);
  for (const name of [
    'GC_ANDROID_KEYSTORE_FILE',
    'GC_ANDROID_KEYSTORE_PASSWORD',
    'GC_ANDROID_KEY_ALIAS',
    'GC_ANDROID_KEY_PASSWORD',
    'GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS',
  ]) {
    assert.ok(signingBlock.includes(`printf '${name}=%s\\n'`));
  }
  assert.match(firebaseFixtureBlock, /\$\{RUNNER_TEMP\}\/gc-google-services-ci\.json/);
  assert.match(firebaseFixtureBlock, /com\.globalconnects\.groupcompanion/);
  assert.match(firebaseFixtureBlock, /CI_COMPILE_FIXTURE_NOT_A_CREDENTIAL/);
  assert.match(firebaseFixtureBlock, /GOOGLE_SERVICES_JSON/);

  const arm64Architecture = buildBlock.indexOf(
    '"-PreactNativeArchitectures=arm64-v8a"',
  );
  const assembleRelease = buildBlock.indexOf('assembleRelease', arm64Architecture);
  const stageApk = buildBlock.indexOf('node scripts/stage-android-apk.js stage');
  const allArchitectures = buildBlock.indexOf(
    '"-PreactNativeArchitectures=armeabi-v7a,arm64-v8a,x86,x86_64"',
  );
  const bundleRelease = buildBlock.indexOf('bundleRelease', allArchitectures);
  const verifyApk = buildBlock.indexOf('node scripts/stage-android-apk.js verify');
  assert.ok(
    arm64Architecture >= 0
      && arm64Architecture < assembleRelease
      && assembleRelease < stageApk
      && stageApk < allArchitectures
      && allArchitectures < bundleRelease
      && bundleRelease < verifyApk,
  );
  assert.match(
    buildBlock.slice(stageApk, allArchitectures),
    /outputs\/android-staging\/app-release-arm64-v8a\.apk[\s\S]*arm64-v8a/,
  );
  assert.match(
    buildBlock.slice(verifyApk),
    /outputs\/android-staging\/app-release-arm64-v8a\.apk[\s\S]*arm64-v8a/,
  );
  assert.doesNotMatch(androidJob, /debug\.keystore|androiddebugkey/);
});

test('template drift and damaged markers fail closed', () => {
  assert.throws(
    () => plugin.patchAppBuildGradle(
      GENERATED_GRADLE_FIXTURE.replace(
        'signingConfig signingConfigs.debug\n            minifyEnabled true',
        'minifyEnabled true',
      ),
    ),
    /debug signing fallback/,
  );

  assert.throws(
    () => plugin.patchAppBuildGradle(
      `${GENERATED_GRADLE_FIXTURE}\n// @generated by with-android-release-signing: declarations`,
    ),
    /incomplete or duplicate generated Gradle markers/,
  );
});
