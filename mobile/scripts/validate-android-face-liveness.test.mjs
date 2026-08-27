import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const plugin = require('../plugins/with-android-face-liveness');

const OPTIONS = Object.freeze({
  enabled: true,
  region: 'ap-south-1',
  identityPoolId: 'ap-south-1:11111111-1111-4111-8111-111111111111',
});

test('native Face Liveness is disabled by default and validates opt-in public identifiers', () => {
  assert.deepEqual(plugin.resolveFaceLivenessOptions(), {
    enabled: false,
    region: null,
    identityPoolId: null,
  });
  assert.deepEqual(plugin.resolveFaceLivenessOptions(OPTIONS), OPTIONS);
  assert.throws(
    () => plugin.resolveFaceLivenessOptions({ ...OPTIONS, region: 'not-a-region' }),
    /bounded AWS region/,
  );
  assert.throws(
    () => plugin.resolveFaceLivenessOptions({ ...OPTIONS, identityPoolId: 'us-east-1:11111111-1111-4111-8111-111111111111' }),
    /Identity Pool ID/,
  );
});

test('Gradle mutation is idempotent and adds AWS or Compose only for an enabled native build', () => {
  const projectFixture = `buildscript {
  dependencies {
        classpath('org.jetbrains.kotlin:kotlin-gradle-plugin')
  }
}`;
  const enabledProject = plugin.patchProjectBuildGradle(projectFixture, true);
  assert.match(enabledProject, /kotlin-gradle-plugin:2\.2\.0/);
  assert.match(enabledProject, /org\.jetbrains\.kotlin\.plugin\.compose/);
  assert.equal(plugin.patchProjectBuildGradle(enabledProject, true), enabledProject);
  assert.equal(plugin.patchProjectBuildGradle(enabledProject, false), projectFixture);

  const appFixture = `apply plugin: "org.jetbrains.kotlin.android"

android {
}

dependencies {
    implementation("com.facebook.react:react-android")
}`;
  const enabledApp = plugin.patchAppBuildGradle(appFixture, true);
  assert.match(enabledApp, /com\.amplifyframework\.ui:liveness:1\.11\.0/);
  assert.match(enabledApp, /com\.amplifyframework:aws-auth-cognito:2\.38\.1/);
  assert.match(enabledApp, /androidx\.compose:compose-bom:2026\.03\.00/);
  assert.match(enabledApp, /coreLibraryDesugaringEnabled true/);
  assert.equal(plugin.patchAppBuildGradle(enabledApp, true), enabledApp);
  const disabledApp = plugin.patchAppBuildGradle(enabledApp, false);
  assert.doesNotMatch(disabledApp, /amplifyframework|plugin\.compose|compose-bom/);
});

test('manual React package registration remains bounded and idempotent', () => {
  const fixture = `PackageList(this).packages.apply {
        // Packages
      }`;
  const patched = plugin.patchMainApplication(fixture);
  assert.match(patched, /add\(GCFaceLivenessPackage\(\)\)/);
  assert.equal(plugin.patchMainApplication(patched), patched);
});

test('generated Cognito configuration contains public locators but no static AWS credentials', () => {
  const configuration = plugin.amplifyConfiguration(OPTIONS);
  assert.match(configuration, /ap-south-1:11111111-1111-4111-8111-111111111111/);
  assert.match(configuration, /CognitoIdentity/);
  assert.doesNotMatch(configuration, /access.?key|secret.?key|session.?token/i);
});

test('enabled and disabled native templates preserve the no-frames/no-secrets bridge contract', async () => {
  const temporaryRoot = await fs.mkdtemp(path.join(os.tmpdir(), 'gc-face-liveness-'));
  try {
    await plugin.writeNativeFiles(temporaryRoot, 'com.example.app', OPTIONS);
    const sourcePath = path.join(
      temporaryRoot,
      'app/src/main/java/com/example/app/GCFaceLivenessPackage.kt',
    );
    const configPath = path.join(
      temporaryRoot,
      'app/src/main/res/raw/gc_face_liveness_amplifyconfiguration.json',
    );
    const enabledSource = await fs.readFile(sourcePath, 'utf8');
    assert.match(enabledSource, /FaceLivenessDetector\(/);
    assert.match(enabledSource, /FLAG_SECURE/);
    assert.ok(
      enabledSource.indexOf('addFlags(WindowManager.LayoutParams.FLAG_SECURE)')
        < enabledSource.indexOf('setContentView(composeView)'),
      'FLAG_SECURE must be configured before sensitive content is attached',
    );
    assert.ok(
      enabledSource.indexOf('addFlags(WindowManager.LayoutParams.FLAG_SECURE)')
        < enabledSource.indexOf('nextDialog.show()'),
      'FLAG_SECURE must be configured before the dialog becomes visible',
    );
    assert.match(enabledSource, /mainHandler\.postDelayed\(deadline, remainingMillis\)/);
    assert.match(enabledSource, /mainHandler\.removeCallbacks\(it\)/);
    assert.match(enabledSource, /VERSION_CODES\.P/);
    assert.doesNotMatch(enabledSource, /VERSION_CODES\.O\s*&&/);
    assert.match(enabledSource, /AWSCognitoAuthPlugin/);
    assert.doesNotMatch(enabledSource, /access.?key|secret.?key|session.?token/i);
    assert.doesNotMatch(enabledSource, /ByteArray|Bitmap|ImageProxy|videoFrame/);
    assert.match(await fs.readFile(configPath, 'utf8'), /ap-south-1/);

    const controllerSource = await fs.readFile(
      new URL('../src/features/my-photos/hooks/use-face-scan-controller.ts', import.meta.url),
      'utf8',
    );
    assert.match(controllerSource, /MAX_LIVENESS_SESSION_LIFETIME_MS = 3 \* 60_000/);
    assert.doesNotMatch(controllerSource, /15 \* 60_000/);

    await plugin.writeNativeFiles(
      temporaryRoot,
      'com.example.app',
      plugin.resolveFaceLivenessOptions(),
    );
    const disabledSource = await fs.readFile(sourcePath, 'utf8');
    assert.match(disabledSource, /"available" to false/);
    assert.doesNotMatch(disabledSource, /amplifyframework\.ui\.liveness|AWSCognitoAuthPlugin/);
    await assert.rejects(fs.access(configPath));
  } finally {
    await fs.rm(temporaryRoot, { recursive: true, force: true });
  }
});
