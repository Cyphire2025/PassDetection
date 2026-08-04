const fs = require('node:fs/promises');
const path = require('node:path');

const { withDangerousMod } = require('@expo/config-plugins');

const MARKER = '# Preserve Expo headless app loader reflection targets.';
const KEEP_RULES = `${MARKER}
-keep class expo.modules.adapters.react.apploader.** { *; }
`;

/**
 * Expo resolves RNHeadlessAppLoader by class name. R8 cannot discover that
 * reflective edge, so release minification needs an explicit keep rule.
 */
module.exports = function withExpoHeadlessLoaderProguard(config) {
  return withDangerousMod(config, [
    'android',
    async (dangerousConfig) => {
      const rulesPath = path.join(
        dangerousConfig.modRequest.platformProjectRoot,
        'app',
        'proguard-rules.pro',
      );
      const current = await fs.readFile(rulesPath, 'utf8');
      if (!current.includes(MARKER)) {
        const separator = current.endsWith('\n') ? '\n' : '\n\n';
        await fs.writeFile(rulesPath, `${current}${separator}${KEEP_RULES}`, 'utf8');
      }
      return dangerousConfig;
    },
  ]);
};
