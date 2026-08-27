import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  REVIEWED_ANDROID_BUILD_TOOLS_VERSION,
  REVIEWED_GRADLE_DISTRIBUTION_SHA256,
  REVIEWED_GRADLE_DISTRIBUTION_URL,
  REVIEWED_GRADLE_VERSION,
  validateReviewedGradleWrapper,
} = require('./android-release-toolchain.js');

const wrapperSource = [
  'distributionBase=GRADLE_USER_HOME',
  'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.3.1-bin.zip',
  `distributionSha256Sum=${REVIEWED_GRADLE_DISTRIBUTION_SHA256}`,
  'networkTimeout=10000',
  '',
].join('\n');

test('pins the reviewed Android and Gradle release toolchain', () => {
  assert.equal(REVIEWED_ANDROID_BUILD_TOOLS_VERSION, '37.0.0');
  assert.equal(REVIEWED_GRADLE_VERSION, '9.3.1');
  assert.equal(
    REVIEWED_GRADLE_DISTRIBUTION_URL,
    'https://services.gradle.org/distributions/gradle-9.3.1-bin.zip',
  );
  assert.equal(
    REVIEWED_GRADLE_DISTRIBUTION_SHA256,
    'b266d5ff6b90eada6dc3b20cb090e3731302e553a27c5d3e4df1f0d76beaff06',
  );
  assert.deepEqual(validateReviewedGradleWrapper(wrapperSource), {
    distributionSha256: REVIEWED_GRADLE_DISTRIBUTION_SHA256,
    distributionUrl: REVIEWED_GRADLE_DISTRIBUTION_URL,
    version: REVIEWED_GRADLE_VERSION,
  });
});

test('rejects a changed, missing, or duplicated Gradle distribution checksum', () => {
  assert.throws(
    () => validateReviewedGradleWrapper(
      wrapperSource.replace(REVIEWED_GRADLE_DISTRIBUTION_SHA256, '0'.repeat(64)),
    ),
    /distribution checksum is invalid/,
  );
  assert.throws(
    () => validateReviewedGradleWrapper(
      wrapperSource.replace(/^distributionSha256Sum=.*\r?\n/m, ''),
    ),
    /exactly one distributionSha256Sum/,
  );
  assert.throws(
    () => validateReviewedGradleWrapper(
      `${wrapperSource}distributionSha256Sum=${REVIEWED_GRADLE_DISTRIBUTION_SHA256}\n`,
    ),
    /exactly one distributionSha256Sum/,
  );
  assert.throws(
    () => validateReviewedGradleWrapper(
      wrapperSource.replace('gradle-9.3.1-bin.zip', 'gradle-9.4.1-bin.zip'),
    ),
    /must use reviewed Gradle 9\.3\.1/,
  );
});
