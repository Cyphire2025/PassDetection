import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  patchMainApplication,
  writeNativeSource,
} = require('../plugins/with-android-unlocked-device-store.js');

const mainApplication = `package com.example.enterprise

class MainApplication {
  val packages =
    PackageList(this).packages.apply {
      // add(MyReactNativePackage())
    }
}
`;

test('registers the package exactly once and fails when the Expo seam changes', () => {
  const patched = patchMainApplication(mainApplication);
  const patchedTwice = patchMainApplication(patched);

  assert.equal(patchedTwice, patched);
  assert.equal(
    patched.match(/add\(GCUnlockedDeviceStorePackage\(\)\)/g)?.length,
    1,
  );
  assert.throws(
    () => patchMainApplication('class MainApplication'),
    /could not find the PackageList registration block/,
  );
});

test('generates the API-gated Android Keystore implementation in the app package', async () => {
  const projectRoot = await mkdtemp(path.join(tmpdir(), 'gc-unlocked-device-store-'));
  try {
    await writeNativeSource(projectRoot, 'com.example.enterprise');
    const sourcePath = path.join(
      projectRoot,
      'app',
      'src',
      'main',
      'java',
      'com',
      'example',
      'enterprise',
      'GCUnlockedDeviceStorePackage.kt',
    );
    const source = await readFile(sourcePath, 'utf8');

    assert.match(source, /^package com\.example\.enterprise/m);
    assert.match(source, /Build\.VERSION_CODES\.VANILLA_ICE_CREAM/);
    assert.match(source, /setUnlockedDeviceRequired\(true\)/);
    assert.match(source, /FEATURE_STRONGBOX_KEYSTORE/);
    assert.match(source, /setIsStrongBoxBacked\(true\)/);
    assert.match(source, /catch \(_: StrongBoxUnavailableException\)/);
    assert.match(source, /keyInfo\.isInsideSecureHardware/);
    assert.match(source, /SECURITY_LEVEL_STRONGBOX/);
    assert.match(source, /AES\/GCM\/NoPadding/);
    assert.match(source, /MAX_ENCODED_VALUE_CHARS/);
    assert.match(source, /keyguardManager\.isDeviceLocked/);
    assert.match(source, /userManager\.isUserUnlocked/);
    assert.match(source, /SECURE_VALUE_REQUIRES_UNLOCK/);
    assert.match(source, /Deletion intentionally remains available while locked/);
    assert.doesNotMatch(source, /__ANDROID_PACKAGE__/);
  } finally {
    await rm(projectRoot, { recursive: true, force: true });
  }
});
