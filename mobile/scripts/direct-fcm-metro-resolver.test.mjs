import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { withDirectFcmNotifications } = require('./direct-fcm-metro-resolver.js');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const notificationsRoot = path.dirname(require.resolve('expo-notifications/package.json'));
const replacement = path.join(root, 'src/core/notifications/expo-relay-disabled.ts');

test('suppresses both pinned Expo relay module entry paths before their side effects run', () => {
  for (const entry of ['build/DevicePushTokenAutoRegistration.fx.js', 'src/DevicePushTokenAutoRegistration.fx.ts']) {
    const context = { resolveRequest: () => ({ type: 'sourceFile', filePath: path.join(notificationsRoot, entry) }) };
    const configured = withDirectFcmNotifications({}, root);
    assert.deepEqual(configured.resolver.resolveRequest(context, './DevicePushTokenAutoRegistration.fx', 'android'), {
      type: 'sourceFile', filePath: replacement,
    });
  }
});

test('preserves Sentry and other resolver behavior, including token acquisition and permissions', () => {
  const entries = [
    path.join(notificationsRoot, 'build/getDevicePushTokenAsync.js'),
    path.join(notificationsRoot, 'build/TokenEmitter.js'),
    path.join(notificationsRoot, 'build/NotificationPermissions.js'),
    path.join(root, 'another/DevicePushTokenAutoRegistration.fx.js'),
  ];
  for (const filePath of entries) {
    const expected = { type: 'sourceFile', filePath };
    const config = { transformer: { sentry: true }, resolver: { sourceExts: ['ts'],
      resolveRequest: (context, name, platform) => {
        assert.equal(name, 'requested-module');
        assert.equal(platform, 'android');
        return expected;
      } } };
    const configured = withDirectFcmNotifications(config, root);
    assert.equal(configured.transformer, config.transformer);
    assert.equal(configured.resolver.sourceExts, config.resolver.sourceExts);
    assert.equal(configured.resolver.resolveRequest({}, 'requested-module', 'android'), expected);
  }
});

test('preserves asset and empty resolutions', () => {
  for (const expected of [{ type: 'assetFiles', filePaths: ['icon.png'] }, { type: 'empty' }]) {
    const configured = withDirectFcmNotifications({}, root);
    assert.equal(configured.resolver.resolveRequest({ resolveRequest: () => expected }, 'asset', 'android'), expected);
  }
});

test('the app Metro config actually applies the relay suppression', () => {
  const configured = require('../metro.config.js');
  const context = { resolveRequest: () => ({ type: 'sourceFile',
    filePath: path.join(notificationsRoot, 'build/DevicePushTokenAutoRegistration.fx.js') }) };
  assert.equal(configured.resolver.resolveRequest(context, './DevicePushTokenAutoRegistration.fx', 'android').filePath,
    replacement);
});
