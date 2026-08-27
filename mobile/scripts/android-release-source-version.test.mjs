import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  assertAndroidVersionMetadata,
  parseAndroidSourceVersion,
} = require('./android-release-source-version.js');

const CONFIG = `export default {
    version: "1.0.2",
    ios: {
      buildNumber: "2",
    },
    android: {
      versionCode: 3,
    },
};`;

test('parses one source version and requires package.json parity', () => {
  assert.deepEqual(
    parseAndroidSourceVersion(CONFIG, { version: '1.0.2' }),
    { versionCode: 3, versionName: '1.0.2' },
  );
  assert.throws(
    () => parseAndroidSourceVersion(CONFIG, { version: '1.0.0' }),
    /must match/,
  );
});

test('requires APK metadata to match source version name and code exactly', () => {
  const expected = { versionCode: 3, versionName: '1.0.2' };
  assert.deepEqual(assertAndroidVersionMetadata(expected, expected), expected);
  assert.throws(
    () => assertAndroidVersionMetadata({ versionCode: 2, versionName: '1.0.2' }, expected),
    /must exactly match/,
  );
  assert.throws(
    () => assertAndroidVersionMetadata({ versionCode: 3, versionName: '1.0.0' }, expected),
    /must exactly match/,
  );
});

test('rejects ambiguous or invalid app config version declarations', () => {
  assert.throws(
    () => parseAndroidSourceVersion(`${CONFIG}\n    version: "2.0.0",`, { version: '1.0.2' }),
    /exactly one top-level Expo version/,
  );
  assert.throws(
    () => parseAndroidSourceVersion(CONFIG.replace('versionCode: 3', 'versionCode: 0'), { version: '1.0.2' }),
    /version code is invalid/,
  );
});
