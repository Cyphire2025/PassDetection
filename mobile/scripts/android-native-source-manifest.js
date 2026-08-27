'use strict';

const { createHash } = require('node:crypto');
const { Buffer } = require('node:buffer');
const {
  lstatSync,
  readFileSync,
  readdirSync,
} = require('node:fs');
const { join, relative, resolve } = require('node:path');

const REQUIRED_ANDROID_NATIVE_FILES = Object.freeze([
  'android/app/build.gradle',
  'android/app/google-services.json',
  'android/app/proguard-rules.pro',
  'android/build.gradle',
  'android/gradle.properties',
  'android/gradle/wrapper/gradle-wrapper.jar',
  'android/gradle/wrapper/gradle-wrapper.properties',
  'android/gradlew',
  'android/gradlew.bat',
  'android/sentry.properties',
  'android/settings.gradle',
]);

const ANDROID_NATIVE_EXCLUSIONS = Object.freeze([
  'android/.gradle/',
  'android/.kotlin/',
  'android/**/.cxx/',
  'android/**/build/',
  'android/**/captures/',
  'android/local.properties',
  'android/**/*.jks',
  'android/**/*.keystore',
  'native signing credentials and generated build outputs',
]);

function sha256Bytes(value) {
  return createHash('sha256').update(value).digest('hex').toUpperCase();
}

function validateNativeAndroidSourceSnapshot(snapshot) {
  const entries = snapshot?.manifest?.entries;
  if (
    snapshot?.manifest?.schema_version !== 2
    || snapshot?.manifest?.root !== 'mobile/android'
    || typeof snapshot?.manifest?.selection !== 'string'
    || !Array.isArray(snapshot?.manifest?.exclusions)
    || !Array.isArray(entries)
    || entries.length === 0
    || snapshot?.file_count !== entries.length
    || !Number.isSafeInteger(snapshot?.total_bytes)
    || snapshot.total_bytes < 0
  ) {
    throw new Error('The Android native release source snapshot is invalid.');
  }
  const paths = new Set();
  let totalBytes = 0;
  for (const entry of entries) {
    if (
      typeof entry?.path !== 'string'
      || !entry.path.startsWith('android/')
      || entry.path.includes('\\')
      || !Number.isSafeInteger(entry?.bytes)
      || entry.bytes < 0
      || !/^[0-9A-F]{64}$/.test(entry?.sha256 || '')
      || paths.has(entry.path)
    ) {
      throw new Error('The Android native release source snapshot is invalid.');
    }
    paths.add(entry.path);
    totalBytes += entry.bytes;
  }
  const expectedHash = sha256Bytes(
    Buffer.from(`${JSON.stringify(snapshot.manifest)}\n`, 'utf8'),
  );
  if (snapshot.total_bytes !== totalBytes || snapshot.sha256 !== expectedHash) {
    throw new Error('The Android native release source snapshot hash is invalid.');
  }
  return snapshot;
}

function assertSecretSafeProperties(bytes, path) {
  const source = bytes.toString('utf8');
  for (const line of source.split(/\r?\n/)) {
    const property = line.match(/^\s*([^#!][^=:\s]*)\s*[:=]/)?.[1] || '';
    if (/(?:password|passwd|secret|token|private.?key|keystore.?pass)/i.test(property)) {
      throw new Error(`${path} contains a secret-like property and cannot enter release evidence.`);
    }
    if (path === 'android/sentry.properties' && property === 'defaults.url') {
      const rawValue = line.replace(/^\s*[^=:\s]+\s*[:=]\s*/, '').trim();
      let parsed;
      try {
        parsed = new URL(rawValue);
      } catch {
        throw new Error('android/sentry.properties defaults.url must be a safe HTTPS URL.');
      }
      if (
        parsed.protocol !== 'https:'
        || parsed.username
        || parsed.password
        || parsed.search
        || parsed.hash
      ) {
        throw new Error('android/sentry.properties defaults.url must be a safe HTTPS URL.');
      }
    }
  }
}

function assertSecretSafeGradleProperties(bytes) {
  assertSecretSafeProperties(bytes, 'android/gradle.properties');
}

function listFiles(directory, dependencies = {}) {
  const list = dependencies.readdir || readdirSync;
  const inspect = dependencies.lstat || lstatSync;
  const files = [];
  const visit = (current) => {
    for (const entry of list(current, { withFileTypes: true })) {
      const absolutePath = join(current, entry.name);
      if (entry.isDirectory()) {
        if (['.cxx', '.gradle', '.kotlin', 'build', 'captures'].includes(entry.name)) continue;
        visit(absolutePath);
      } else {
        const metadata = inspect(absolutePath);
        if (!entry.isFile() || !metadata.isFile() || metadata.isSymbolicLink()) {
          throw new Error('The Android native release snapshot contains an unsupported entry.');
        }
        if (
          entry.name !== 'local.properties'
          && !/\.(?:jks|keystore)$/i.test(entry.name)
        ) {
          files.push(absolutePath);
        }
      }
    }
  };
  visit(directory);
  return files;
}

function nativeAndroidSourceManifest(mobileRoot, dependencies = {}) {
  const root = resolve(mobileRoot);
  const inspect = dependencies.lstat || lstatSync;
  const readBytes = dependencies.readFile || readFileSync;
  const sourceRoot = join(root, 'android');
  const sourceRootMetadata = inspect(sourceRoot);
  if (!sourceRootMetadata.isDirectory() || sourceRootMetadata.isSymbolicLink()) {
    throw new Error('Generated Android source is unavailable or unsafe for release evidence.');
  }
  const absoluteFiles = listFiles(sourceRoot, dependencies);
  const uniqueFiles = [...new Set(absoluteFiles.map((path) => resolve(path)))].sort();
  const entries = uniqueFiles.map((absolutePath) => {
    const metadata = inspect(absolutePath);
    if (!metadata.isFile() || metadata.isSymbolicLink()) {
      throw new Error('A required Android native release source file is unavailable or unsafe.');
    }
    const path = relative(root, absolutePath).replaceAll('\\', '/');
    const bytes = readBytes(absolutePath);
    if (path === 'android/gradle.properties' || path === 'android/sentry.properties') {
      assertSecretSafeProperties(bytes, path);
    }
    return Object.freeze({
      bytes: bytes.length,
      path,
      sha256: sha256Bytes(bytes),
    });
  });
  const availablePaths = new Set(entries.map((entry) => entry.path));
  for (const requiredPath of REQUIRED_ANDROID_NATIVE_FILES) {
    if (!availablePaths.has(requiredPath)) {
      throw new Error(`Required Android native release input is missing: ${requiredPath}.`);
    }
  }
  const manifest = Object.freeze({
    schema_version: 2,
    root: 'mobile/android',
    selection: 'all Android native build inputs except generated outputs, local SDK paths, and signing credentials',
    exclusions: ANDROID_NATIVE_EXCLUSIONS,
    entries,
  });
  return validateNativeAndroidSourceSnapshot(Object.freeze({
    file_count: entries.length,
    total_bytes: entries.reduce((total, entry) => total + entry.bytes, 0),
    sha256: sha256Bytes(Buffer.from(`${JSON.stringify(manifest)}\n`, 'utf8')),
    manifest,
  }));
}

module.exports = {
  ANDROID_NATIVE_EXCLUSIONS,
  REQUIRED_ANDROID_NATIVE_FILES,
  assertSecretSafeGradleProperties,
  assertSecretSafeProperties,
  nativeAndroidSourceManifest,
  validateNativeAndroidSourceSnapshot,
};
