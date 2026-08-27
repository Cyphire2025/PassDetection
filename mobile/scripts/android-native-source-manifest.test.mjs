import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import {
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  REQUIRED_ANDROID_NATIVE_FILES,
  nativeAndroidSourceManifest,
} = require('./android-native-source-manifest.js');

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'gc-native-snapshot-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const path of REQUIRED_ANDROID_NATIVE_FILES) {
    const absolutePath = join(root, ...path.split('/'));
    mkdirSync(dirname(absolutePath), { recursive: true });
    writeFileSync(absolutePath, path === 'android/gradle.properties'
      ? 'reactNativeArchitectures=armeabi-v7a,arm64-v8a,x86,x86_64\n'
      : path === 'android/sentry.properties'
        ? 'defaults.url=https://sentry.io/\n'
      : `fixture:${path}`);
  }
  const mainSource = join(root, 'android', 'app', 'src', 'main', 'AndroidManifest.xml');
  mkdirSync(dirname(mainSource), { recursive: true });
  writeFileSync(mainSource, '<manifest/>');
  mkdirSync(join(root, 'android', 'app', 'build'), { recursive: true });
  writeFileSync(join(root, 'android', 'app', 'build', 'generated.bin'), 'ignored');
  writeFileSync(join(root, 'android', 'local.properties'), 'sdk.dir=ignored');
  writeFileSync(join(root, 'android', 'release-input.gradle'), 'releaseInput=true');
  return { mainSource, root };
}

test('hashes all safe native inputs and excludes generated, local, and credential files', (t) => {
  const { root } = fixture(t);
  const snapshot = nativeAndroidSourceManifest(root);
  const paths = snapshot.manifest.entries.map((entry) => entry.path);
  assert.ok(paths.includes('android/app/src/main/AndroidManifest.xml'));
  assert.ok(paths.includes('android/app/build.gradle'));
  assert.ok(paths.includes('android/app/google-services.json'));
  assert.ok(paths.includes('android/gradle.properties'));
  assert.ok(paths.includes('android/sentry.properties'));
  assert.ok(paths.includes('android/release-input.gradle'));
  assert.equal(paths.some((path) => path.includes('/build/generated')), false);
  assert.equal(paths.includes('android/local.properties'), false);
  assert.equal(snapshot.manifest.schema_version, 2);
  assert.match(snapshot.sha256, /^[0-9A-F]{64}$/);
});

test('native source mutations change the snapshot hash', (t) => {
  const { mainSource, root } = fixture(t);
  const before = nativeAndroidSourceManifest(root).sha256;
  writeFileSync(mainSource, '<manifest android:versionName="changed"/>');
  assert.notEqual(nativeAndroidSourceManifest(root).sha256, before);
});

test('rejects secret-like gradle properties instead of hashing them', (t) => {
  const { root } = fixture(t);
  writeFileSync(join(root, 'android', 'gradle.properties'), 'releaseStorePassword=do-not-hash\n');
  assert.throws(
    () => nativeAndroidSourceManifest(root),
    /secret-like property/,
  );
});

test('rejects secret-bearing or unsafe Sentry native properties', (t) => {
  const { root } = fixture(t);
  writeFileSync(join(root, 'android', 'sentry.properties'), 'auth.token=do-not-hash\n');
  assert.throws(
    () => nativeAndroidSourceManifest(root),
    /sentry\.properties contains a secret-like property/,
  );
  writeFileSync(
    join(root, 'android', 'sentry.properties'),
    'defaults.url=https://user:password@sentry.example/path\n',
  );
  assert.throws(
    () => nativeAndroidSourceManifest(root),
    /safe HTTPS URL/,
  );
});
