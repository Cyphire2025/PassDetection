const fs = require('node:fs/promises');
const path = require('node:path');

const {
  withDangerousMod,
  withMainApplication,
} = require('@expo/config-plugins');

const MODULE_NAME = 'GCUnlockedDeviceStore';
const PACKAGE_REGISTRATION = '          add(GCUnlockedDeviceStorePackage())';
const TEMPLATE_PATH = path.join(
  __dirname,
  'android-unlocked-device-store',
  'GCUnlockedDeviceStorePackage.kt.template',
);

function assertAndroidPackage(value) {
  if (typeof value !== 'string' || !/^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$/.test(value)) {
    throw new Error(
      `${MODULE_NAME} requires a valid Expo android.package before prebuild.`,
    );
  }
  return value;
}

function patchMainApplication(contents) {
  if (contents.includes(PACKAGE_REGISTRATION.trim())) return contents;

  const packageListAnchor = /(PackageList\(this\)\.packages\.apply \{\r?\n)/;
  if (!packageListAnchor.test(contents)) {
    throw new Error(
      `${MODULE_NAME} could not find the PackageList registration block in MainApplication.kt.`,
    );
  }
  return contents.replace(packageListAnchor, `$1${PACKAGE_REGISTRATION}\n`);
}

async function writeNativeSource(platformProjectRoot, androidPackage) {
  const template = await fs.readFile(TEMPLATE_PATH, 'utf8');
  const rendered = template.replaceAll('__ANDROID_PACKAGE__', androidPackage);
  const destination = path.join(
    platformProjectRoot,
    'app',
    'src',
    'main',
    'java',
    ...androidPackage.split('.'),
    'GCUnlockedDeviceStorePackage.kt',
  );
  await fs.mkdir(path.dirname(destination), { recursive: true });

  let current = null;
  try {
    current = await fs.readFile(destination, 'utf8');
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  if (current !== rendered) await fs.writeFile(destination, rendered, 'utf8');
}

module.exports = function withAndroidUnlockedDeviceStore(config) {
  const androidPackage = assertAndroidPackage(config.android?.package);
  let nextConfig = withMainApplication(config, (mainApplicationConfig) => {
    mainApplicationConfig.modResults.contents = patchMainApplication(
      mainApplicationConfig.modResults.contents,
    );
    return mainApplicationConfig;
  });
  nextConfig = withDangerousMod(nextConfig, [
    'android',
    async (dangerousConfig) => {
      await writeNativeSource(
        dangerousConfig.modRequest.platformProjectRoot,
        androidPackage,
      );
      return dangerousConfig;
    },
  ]);
  return nextConfig;
};

module.exports.patchMainApplication = patchMainApplication;
module.exports.writeNativeSource = writeNativeSource;
