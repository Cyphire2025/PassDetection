'use strict';

const path = require('node:path');

function withDirectFcmNotifications(config, projectRoot) {
  const notificationsRoot = path.dirname(require.resolve('expo-notifications/package.json', {
    paths: [projectRoot],
  }));
  const relayModules = new Set([
    path.join(notificationsRoot, 'build', 'DevicePushTokenAutoRegistration.fx.js'),
    path.join(notificationsRoot, 'src', 'DevicePushTokenAutoRegistration.fx.ts'),
  ]);
  const replacement = path.join(projectRoot, 'src/core/notifications/expo-relay-disabled.ts');
  const previousResolver = config.resolver?.resolveRequest;
  return {
    ...config,
    resolver: {
      ...config.resolver,
      resolveRequest(context, moduleName, platform) {
        const resolved = previousResolver
          ? previousResolver(context, moduleName, platform)
          : context.resolveRequest(context, moduleName, platform);
        return resolved.type === 'sourceFile' && relayModules.has(path.normalize(resolved.filePath))
          ? { ...resolved, filePath: replacement }
          : resolved;
      },
    },
  };
}

module.exports = { withDirectFcmNotifications };
