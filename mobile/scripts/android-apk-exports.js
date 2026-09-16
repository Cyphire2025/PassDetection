'use strict';

const { lstatSync, readdirSync, realpathSync, unlinkSync } = require('node:fs');
const { basename, dirname, join, resolve } = require('node:path');

const APK_NAME = /^GC-App-(\d+\.\d+\.\d+)(-Emulator)?\.apk$/;

function simpleAndroidApkName({ expectedAbi, versionName }) {
  if (!['arm64-v8a', 'x86_64'].includes(expectedAbi)) {
    throw new Error('APK export requires the phone or emulator build variant.');
  }
  if (!/^\d+\.\d+\.\d+$/.test(versionName)) {
    throw new Error('APK export requires a numeric major.minor.patch version.');
  }
  return `GC-App-${versionName}${expectedAbi === 'x86_64' ? '-Emulator' : ''}.apk`;
}

function compareVersions(left, right) {
  const a = left.version.split('.').map(BigInt);
  const b = right.version.split('.').map(BigInt);
  for (let index = 0; index < a.length; index += 1) {
    if (a[index] !== b[index]) return a[index] > b[index] ? -1 : 1;
  }
  return left.name.localeCompare(right.name);
}

// Only call after the new APK and receipt have passed all packaging checks.
// The managed directory is flat: never follow links, recurse, or delete evidence.
function retainLatestAndroidApks({ artifactPath, mobileRoot }) {
  const managedDirectory = resolve(mobileRoot, 'outputs', 'apk');
  if (resolve(dirname(artifactPath)) !== managedDirectory) {
    return Object.freeze({ removed: [], skipped: 'outside_managed_export_directory' });
  }
  const directory = realpathSync(managedDirectory);
  const normalizePath = (value) => process.platform === 'win32' ? value.toLowerCase() : value;
  if (normalizePath(directory) !== normalizePath(managedDirectory)) {
    throw new Error('APK retention does not follow linked export directories or ancestors.');
  }
  const currentName = basename(artifactPath);
  const current = APK_NAME.exec(currentName);
  if (!current || !lstatSync(artifactPath).isFile()) {
    throw new Error('Verified APK export is not a regular managed artifact.');
  }
  const candidates = readdirSync(managedDirectory, { withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => ({ entry, match: APK_NAME.exec(entry.name) }))
    .filter(({ match }) => match && match[2] === current[2])
    .map(({ entry, match }) => ({ name: entry.name, version: match[1] }))
    .sort(compareVersions);
  const keep = candidates.slice(0, 2);
  if (!keep.some((candidate) => candidate.name === currentName)) {
    return Object.freeze({ removed: [], skipped: 'older_version_exported' });
  }
  const stale = candidates.slice(2).map(({ name }) => join(managedDirectory, name));
  // Resolve and validate every exact target before the first deletion.
  for (const target of stale) {
    if (!lstatSync(target).isFile() || dirname(realpathSync(target)) !== directory) {
      throw new Error('APK retention target is outside the managed export directory.');
    }
  }
  for (const target of stale) unlinkSync(target);
  return Object.freeze({ removed: stale.map((target) => basename(target)), skipped: null });
}

module.exports = { retainLatestAndroidApks, simpleAndroidApkName };
