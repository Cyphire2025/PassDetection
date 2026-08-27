'use strict';

const fs = require('node:fs/promises');
const path = require('node:path');

const { withDangerousMod } = require('@expo/config-plugins');
const {
  REVIEWED_GRADLE_DISTRIBUTION_SHA256,
  REVIEWED_GRADLE_DISTRIBUTION_URL,
  REVIEWED_GRADLE_VERSION,
  validateReviewedGradleWrapper,
} = require('../scripts/android-release-toolchain');

function propertyMatches(source, name) {
  if (typeof source !== 'string') {
    throw new Error('The generated Gradle wrapper properties are unavailable.');
  }
  return [...source.matchAll(new RegExp(`^${name}=(.*)$`, 'gm'))];
}

function patchGradleWrapperProperties(source) {
  const distributionUrlMatches = propertyMatches(source, 'distributionUrl');
  if (distributionUrlMatches.length !== 1) {
    throw new Error('Generated Gradle wrapper must declare exactly one distributionUrl.');
  }
  const distributionUrl = distributionUrlMatches[0][1].trim().replaceAll('\\:', ':');
  if (distributionUrl !== REVIEWED_GRADLE_DISTRIBUTION_URL) {
    throw new Error(
      `Generated Gradle wrapper must use reviewed Gradle ${REVIEWED_GRADLE_VERSION}.`,
    );
  }

  const checksumMatches = propertyMatches(source, 'distributionSha256Sum');
  if (checksumMatches.length > 1) {
    throw new Error('Generated Gradle wrapper must not declare duplicate distribution checksums.');
  }
  if (
    checksumMatches.length === 1
    && checksumMatches[0][1].trim() !== REVIEWED_GRADLE_DISTRIBUTION_SHA256
  ) {
    throw new Error(
      `Generated Gradle ${REVIEWED_GRADLE_VERSION} distribution checksum is invalid.`,
    );
  }

  let patched = source;
  if (checksumMatches.length === 0) {
    const newline = source.includes('\r\n') ? '\r\n' : '\n';
    patched = source.replace(
      /^distributionUrl=.*$/m,
      `$&${newline}distributionSha256Sum=${REVIEWED_GRADLE_DISTRIBUTION_SHA256}`,
    );
  }
  validateReviewedGradleWrapper(patched);
  return patched;
}

async function writeReviewedGradleWrapper(platformProjectRoot) {
  const wrapperPath = path.join(
    platformProjectRoot,
    'gradle',
    'wrapper',
    'gradle-wrapper.properties',
  );
  const current = await fs.readFile(wrapperPath, 'utf8');
  const patched = patchGradleWrapperProperties(current);
  if (patched !== current) await fs.writeFile(wrapperPath, patched, 'utf8');
}

module.exports = function withAndroidGradleWrapperIntegrity(config) {
  return withDangerousMod(config, [
    'android',
    async (dangerousConfig) => {
      await writeReviewedGradleWrapper(dangerousConfig.modRequest.platformProjectRoot);
      return dangerousConfig;
    },
  ]);
};

module.exports.patchGradleWrapperProperties = patchGradleWrapperProperties;
module.exports.writeReviewedGradleWrapper = writeReviewedGradleWrapper;
