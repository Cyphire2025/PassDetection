'use strict';

const { spawnSync } = require('node:child_process');
const { resolve } = require('node:path');

const GIT_COMMIT_PATTERN = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i;
const SOURCE_FINGERPRINT_HASH_PATTERN = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i;

function normalizedHex(value, pattern, label) {
  if (typeof value !== 'string' || !pattern.test(value.trim())) {
    throw new Error(`${label} is invalid.`);
  }
  return value.trim().toLowerCase();
}

function normalizeGitCommit(value, label = 'Build Git commit hash') {
  return normalizedHex(value, GIT_COMMIT_PATTERN, label);
}

function normalizeSourceFingerprintHash(value) {
  return normalizedHex(
    value,
    SOURCE_FINGERPRINT_HASH_PATTERN,
    'EAS source fingerprint hash',
  );
}

function resolveGitHead(repoRoot = resolve(__dirname, '..')) {
  const result = spawnSync('git', ['rev-parse', '--verify', 'HEAD'], {
    cwd: repoRoot,
    encoding: 'utf8',
    maxBuffer: 1024 * 1024,
    shell: false,
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    throw new Error('Checked-out Git HEAD could not be resolved for release verification.');
  }
  return normalizeGitCommit(result.stdout, 'Checked-out Git HEAD');
}

function verifyReleaseProvenance(options, dependencies = {}) {
  const gitCommitHash = normalizeGitCommit(options.gitCommitHash);
  const sourceFingerprintHash = normalizeSourceFingerprintHash(options.sourceFingerprintHash);
  const checkedOutGitCommitHash = normalizeGitCommit(
    (dependencies.resolveGitHead || resolveGitHead)(options.repoRoot),
    'Checked-out Git HEAD',
  );
  if (checkedOutGitCommitHash !== gitCommitHash) {
    throw new Error('Checked-out Git HEAD does not match the EAS build Git commit hash.');
  }
  return Object.freeze({
    checkedOutGitCommitHash,
    gitCommitHash,
    sourceFingerprintHash,
  });
}

module.exports = {
  GIT_COMMIT_PATTERN,
  SOURCE_FINGERPRINT_HASH_PATTERN,
  normalizeGitCommit,
  normalizeSourceFingerprintHash,
  resolveGitHead,
  verifyReleaseProvenance,
};
