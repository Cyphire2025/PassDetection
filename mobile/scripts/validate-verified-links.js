'use strict';

const VERIFIED_LINK_ORIGIN = 'https://tech.gctravels.com';
const ANDROID_PACKAGE = 'com.globalconnects.groupcompanion';
const DEEP_LINK_PREFIX = '/gc';
const MAX_ASSOCIATION_BYTES = 128 * 1024;
const REQUEST_TIMEOUT_MS = 10_000;

function normalizeAndroidFingerprint(
  value,
  source = 'GC_ANDROID_APP_LINK_SHA256_CERT_FINGERPRINTS',
) {
  const normalized = value.trim().toUpperCase();
  if (!/^(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$/.test(normalized)) {
    throw new Error(
      `${source} must contain colon-separated SHA-256 certificate fingerprints.`,
    );
  }
  return normalized;
}

function parseAndroidFingerprints(value) {
  if (!value) {
    throw new Error(
      'GC_ANDROID_APP_LINK_SHA256_CERT_FINGERPRINTS is required for Android release validation.',
    );
  }

  const fingerprints = value
    .split(',')
    .map((fingerprint) => normalizeAndroidFingerprint(fingerprint));
  return new Set(fingerprints);
}

function validateAndroidAssetLinks(document, expectedFingerprints) {
  if (!Array.isArray(document)) {
    throw new Error('Android assetlinks.json must contain a JSON array.');
  }

  const delegations = document.filter((candidate) => {
    if (!candidate || typeof candidate !== 'object') {
      return false;
    }
    const relationship = Array.isArray(candidate.relation)
      ? candidate.relation
      : [];
    const target = candidate.target;
    return (
      relationship.includes('delegate_permission/common.handle_all_urls') &&
      target &&
      typeof target === 'object' &&
      target.namespace === 'android_app'
    );
  });
  const unexpectedPackages = delegations.filter(
    (statement) => statement.target.package_name !== ANDROID_PACKAGE,
  );
  if (unexpectedPackages.length > 0) {
    throw new Error(
      `Android assetlinks.json delegates verified links to ${unexpectedPackages.length} unexpected package(s).`,
    );
  }
  const statements = delegations.filter(
    (statement) => statement.target.package_name === ANDROID_PACKAGE,
  );

  if (statements.length === 0) {
    throw new Error(
      `Android assetlinks.json has no handle_all_urls statement for ${ANDROID_PACKAGE}.`,
    );
  }

  const publishedFingerprints = new Set();
  for (const statement of statements) {
    const fingerprints = statement.target.sha256_cert_fingerprints;
    if (!Array.isArray(fingerprints) || fingerprints.length === 0) {
      throw new Error('Android assetlinks.json has an empty signing fingerprint list.');
    }
    for (const value of fingerprints) {
      if (typeof value !== 'string') {
        throw new Error('Android assetlinks.json contains a non-string signing fingerprint.');
      }
      publishedFingerprints.add(
        normalizeAndroidFingerprint(value, 'Android assetlinks.json'),
      );
    }
  }
  const missing = [...expectedFingerprints].filter(
    (fingerprint) => !publishedFingerprints.has(fingerprint),
  );
  if (missing.length > 0) {
    throw new Error(
      `Android assetlinks.json is missing ${missing.length} expected production signing fingerprint(s).`,
    );
  }
  const unexpected = [...publishedFingerprints].filter(
    (fingerprint) => !expectedFingerprints.has(fingerprint),
  );
  if (unexpected.length > 0) {
    throw new Error(
      `Android assetlinks.json contains ${unexpected.length} unexpected signing fingerprint(s).`,
    );
  }
}

function pathRulesAllowGc(rules) {
  const allowedPatterns = rules
    .filter((rule) => rule && typeof rule === 'object' && rule.exclude !== true)
    .map((rule) => rule['/'])
    .filter((pattern) => typeof pattern === 'string');

  return (
    allowedPatterns.length === 2 &&
    allowedPatterns.includes(DEEP_LINK_PREFIX) &&
    allowedPatterns.includes(`${DEEP_LINK_PREFIX}/*`)
  );
}

function legacyPathsAllowGc(paths) {
  if (!Array.isArray(paths)) {
    return false;
  }
  const allowedPaths = paths.filter(
    (path) => typeof path === 'string' && !path.startsWith('NOT '),
  );
  return (
    allowedPaths.length === 2 &&
    allowedPaths.includes(DEEP_LINK_PREFIX) &&
    allowedPaths.includes(`${DEEP_LINK_PREFIX}/*`)
  );
}

function validateAppleAppSiteAssociation(document, teamId) {
  if (!/^[A-Z0-9]{10}$/.test(teamId)) {
    throw new Error('GC_APPLE_TEAM_ID must be the 10-character Apple Team ID.');
  }
  const expectedAppId = `${teamId}.${ANDROID_PACKAGE}`;
  const details = document?.applinks?.details;
  if (!Array.isArray(details)) {
    throw new Error(
      'apple-app-site-association must contain applinks.details as an array.',
    );
  }

  const matchingAssociations = details.filter((detail) => {
    if (!detail || typeof detail !== 'object') {
      return false;
    }
    const appIds = [
      ...(typeof detail.appID === 'string' ? [detail.appID] : []),
      ...(Array.isArray(detail.appIDs) ? detail.appIDs : []),
    ];
    return appIds.includes(expectedAppId);
  });

  const validAssociation =
    matchingAssociations.length > 0 &&
    matchingAssociations.every((detail) => {
      const hasComponents = Array.isArray(detail.components);
      const hasLegacyPaths = Array.isArray(detail.paths);
      if (hasComponents === hasLegacyPaths) {
        return false;
      }
      return hasComponents
        ? pathRulesAllowGc(detail.components)
        : legacyPathsAllowGc(detail.paths);
    });

  if (!validAssociation) {
    throw new Error(
      `apple-app-site-association does not allow ${expectedAppId}${DEEP_LINK_PREFIX} links.`,
    );
  }
}

async function fetchAssociationDocument(pathname) {
  const url = new URL(pathname, VERIFIED_LINK_ORIGIN);
  const response = await fetch(url, {
    headers: { accept: 'application/json' },
    redirect: 'manual',
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });

  if (response.status >= 300 && response.status < 400) {
    throw new Error(
      `${url} redirected to ${response.headers.get('location') || 'another URL'}; verified-link files must be served directly.`,
    );
  }
  if (!response.ok) {
    throw new Error(`${url} returned HTTP ${response.status}.`);
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.includes('application/json')) {
    throw new Error(`${url} returned ${contentType || 'no content type'}, not JSON.`);
  }

  const declaredLength = Number(response.headers.get('content-length'));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_ASSOCIATION_BYTES) {
    throw new Error(`${url} exceeds the ${MAX_ASSOCIATION_BYTES}-byte safety limit.`);
  }
  if (!response.body) {
    throw new Error(`${url} returned no response body.`);
  }

  const chunks = [];
  let receivedBytes = 0;
  const reader = response.body.getReader();
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    receivedBytes += value.byteLength;
    if (receivedBytes > MAX_ASSOCIATION_BYTES) {
      await reader.cancel();
      throw new Error(`${url} exceeds the ${MAX_ASSOCIATION_BYTES}-byte safety limit.`);
    }
    chunks.push(value);
  }

  const bytes = new Uint8Array(receivedBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new Error(`${url} did not contain valid JSON.`);
  }
}

async function main() {
  const platform = process.env.GC_LINK_PLATFORM;
  if (!['android', 'ios'].includes(platform)) {
    throw new Error('GC_LINK_PLATFORM must equal android or ios.');
  }

  if (platform === 'android') {
    const expectedFingerprints = parseAndroidFingerprints(
      process.env.GC_ANDROID_APP_LINK_SHA256_CERT_FINGERPRINTS,
    );
    const document = await fetchAssociationDocument(
      '/.well-known/assetlinks.json',
    );
    validateAndroidAssetLinks(document, expectedFingerprints);
  } else {
    const teamId = process.env.GC_APPLE_TEAM_ID;
    if (!teamId) {
      throw new Error('GC_APPLE_TEAM_ID is required for iOS release validation.');
    }
    const document = await fetchAssociationDocument(
      '/.well-known/apple-app-site-association',
    );
    validateAppleAppSiteAssociation(document, teamId);
  }

  console.log(`${platform} verified-link association passed.`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}

module.exports = {
  parseAndroidFingerprints,
  validateAndroidAssetLinks,
  validateAppleAppSiteAssociation,
};
