/* global __dirname */
'use strict';

const { readFileSync } = require('node:fs');
const { join, resolve } = require('node:path');

function boundedVersionName(value, source) {
  const normalized = String(value || '').trim();
  if (
    !normalized
    || normalized.length > 100
    || /[\s'"\\]/.test(normalized)
  ) {
    throw new Error(`${source} Android version name is invalid.`);
  }
  return normalized;
}

function positiveVersionCode(value, source) {
  const normalized = typeof value === 'number' ? value : Number(String(value || '').trim());
  if (!Number.isSafeInteger(normalized) || normalized <= 0) {
    throw new Error(`${source} Android version code is invalid.`);
  }
  return normalized;
}

function oneMatch(source, pattern, description) {
  const matches = [...source.matchAll(pattern)];
  if (matches.length !== 1) {
    throw new Error(`Expected exactly one ${description} declaration in app.config.ts.`);
  }
  return matches[0][1];
}

function parseAndroidSourceVersion(appConfigSource, packageDocument) {
  if (typeof appConfigSource !== 'string' || !packageDocument || typeof packageDocument !== 'object') {
    throw new Error('Android source version inputs are invalid.');
  }
  const appVersion = boundedVersionName(
    oneMatch(
      appConfigSource,
      /^\s{4}version:\s*["']([^"']+)["'],?\s*$/gm,
      'top-level Expo version',
    ),
    'Expo app config',
  );
  const versionCode = positiveVersionCode(
    oneMatch(
      appConfigSource,
      /^\s{6}versionCode:\s*([0-9]+),?\s*$/gm,
      'Android versionCode',
    ),
    'Expo app config',
  );
  const packageVersion = boundedVersionName(packageDocument.version, 'package.json');
  if (appVersion !== packageVersion) {
    throw new Error('Expo app version and package.json version must match for Android release evidence.');
  }
  return Object.freeze({ versionCode, versionName: appVersion });
}

function loadAndroidSourceVersion(mobileRoot = resolve(__dirname, '..')) {
  const root = resolve(mobileRoot);
  const appConfigSource = readFileSync(join(root, 'app.config.ts'), 'utf8');
  const packageDocument = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  return parseAndroidSourceVersion(appConfigSource, packageDocument);
}

function assertAndroidVersionMetadata(actual, expected, source = 'Android artifact') {
  const actualName = boundedVersionName(actual?.versionName, source);
  const actualCode = positiveVersionCode(actual?.versionCode, source);
  const expectedName = boundedVersionName(expected?.versionName, 'Expected source');
  const expectedCode = positiveVersionCode(expected?.versionCode, 'Expected source');
  if (actualName !== expectedName || actualCode !== expectedCode) {
    throw new Error(
      `${source} version must exactly match source version ${expectedName} (${String(expectedCode)}).`,
    );
  }
  return Object.freeze({ versionCode: actualCode, versionName: actualName });
}

module.exports = {
  assertAndroidVersionMetadata,
  boundedVersionName,
  loadAndroidSourceVersion,
  parseAndroidSourceVersion,
  positiveVersionCode,
};
