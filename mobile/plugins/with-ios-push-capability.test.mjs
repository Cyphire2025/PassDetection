import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { compileModsAsync } = require('expo/config-plugins');
const { withNotificationsIOS } = require('expo-notifications/plugin/build/withNotificationsIOS');
const withIosPushCapability = require('./with-ios-push-capability');

for (const enabled of [true, false]) {
  test(`actual iOS plugin chain preserves unrelated entitlements and push enabled=${enabled}`, async () => {
    let config = { name: 'Test', slug: 'test', ios: { entitlements: {
      'com.apple.developer.associated-domains': ['applinks:example.test'],
    } } };
    config = withIosPushCapability(config, { enabled });
    config = withNotificationsIOS(config, {});
    const result = await compileModsAsync(config, {
      projectRoot: fileURLToPath(new URL('..', import.meta.url)),
      platforms: ['ios'], introspect: true,
    });
    assert.equal(result.ios.entitlements['aps-environment'], enabled ? 'development' : undefined);
    assert.deepEqual(result.ios.entitlements['com.apple.developer.associated-domains'], ['applinks:example.test']);
  });
}
