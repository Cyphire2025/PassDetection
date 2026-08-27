'use strict';

const { readFileSync } = require('node:fs');
const { join, resolve } = require('node:path');

const REVIEWED_ANDROID_BUILD_TOOLS_VERSION = '37.0.0';
const REVIEWED_GRADLE_VERSION = '9.3.1';
const REVIEWED_GRADLE_DISTRIBUTION_SHA256 =
  'b266d5ff6b90eada6dc3b20cb090e3731302e553a27c5d3e4df1f0d76beaff06';
const REVIEWED_GRADLE_DISTRIBUTION_URL =
  `https://services.gradle.org/distributions/gradle-${REVIEWED_GRADLE_VERSION}-bin.zip`;

function oneWrapperProperty(source, name) {
  if (typeof source !== 'string') {
    throw new Error('The Gradle wrapper properties are unavailable.');
  }
  const matches = [...source.matchAll(new RegExp(`^${name}=(.+)$`, 'gm'))];
  if (matches.length !== 1) {
    throw new Error(`Gradle wrapper must declare exactly one ${name}.`);
  }
  return matches[0][1].trim();
}

function validateReviewedGradleWrapper(source) {
  const escapedDistributionUrl = oneWrapperProperty(source, 'distributionUrl');
  const distributionUrl = escapedDistributionUrl.replaceAll('\\:', ':');
  if (distributionUrl !== REVIEWED_GRADLE_DISTRIBUTION_URL) {
    throw new Error(`Gradle wrapper must use reviewed Gradle ${REVIEWED_GRADLE_VERSION}.`);
  }
  const distributionSha256 = oneWrapperProperty(source, 'distributionSha256Sum');
  if (distributionSha256 !== REVIEWED_GRADLE_DISTRIBUTION_SHA256) {
    throw new Error(`Gradle ${REVIEWED_GRADLE_VERSION} distribution checksum is invalid.`);
  }
  return Object.freeze({
    distributionSha256,
    distributionUrl,
    version: REVIEWED_GRADLE_VERSION,
  });
}

function loadReviewedGradleWrapper(mobileRoot = resolve(__dirname, '..')) {
  const wrapperPath = join(
    resolve(mobileRoot),
    'android',
    'gradle',
    'wrapper',
    'gradle-wrapper.properties',
  );
  return validateReviewedGradleWrapper(readFileSync(wrapperPath, 'utf8'));
}

module.exports = {
  REVIEWED_ANDROID_BUILD_TOOLS_VERSION,
  REVIEWED_GRADLE_DISTRIBUTION_SHA256,
  REVIEWED_GRADLE_DISTRIBUTION_URL,
  REVIEWED_GRADLE_VERSION,
  loadReviewedGradleWrapper,
  validateReviewedGradleWrapper,
};
