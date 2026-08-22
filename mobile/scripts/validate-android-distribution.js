'use strict';

const { parseApprovedFingerprints } = require('./verify-android-artifact');

function validateAndroidDistributionEnvironment(source = process.env) {
  return parseApprovedFingerprints(
    source.GC_ANDROID_DISTRIBUTION_SHA256_CERT_FINGERPRINTS,
  ).size;
}

if (require.main === module) {
  try {
    const approvedCount = validateAndroidDistributionEnvironment();
    process.stdout.write(
      `Android distribution signer allowlist validated (${approvedCount} approved certificate${approvedCount === 1 ? '' : 's'}).\n`,
    );
  } catch (error) {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  }
}

module.exports = { validateAndroidDistributionEnvironment };
