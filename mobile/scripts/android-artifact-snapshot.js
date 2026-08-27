'use strict';

const { createHash, randomUUID } = require('node:crypto');
const {
  constants: { COPYFILE_EXCL },
  copyFileSync,
  createReadStream,
  lstatSync,
  mkdtempSync,
  rmSync,
  statSync,
} = require('node:fs');
const { tmpdir } = require('node:os');
const { basename, extname, join, resolve } = require('node:path');

function sha256File(filePath) {
  return new Promise((resolveHash, reject) => {
    const digest = createHash('sha256');
    const stream = createReadStream(filePath);
    stream.on('error', reject);
    stream.on('data', (chunk) => digest.update(chunk));
    stream.on('end', () => resolveHash(digest.digest('hex').toUpperCase()));
  });
}

function stableStat(filePath, label) {
  const link = lstatSync(filePath);
  if (link.isSymbolicLink() || !link.isFile() || link.size <= 0) {
    throw new Error(`${label} must be a non-empty regular file, not a symbolic link.`);
  }
  const stat = statSync(filePath);
  return Object.freeze({
    birthtimeMs: stat.birthtimeMs,
    ctimeMs: stat.ctimeMs,
    dev: stat.dev,
    ino: stat.ino,
    mode: stat.mode,
    mtimeMs: stat.mtimeMs,
    size: stat.size,
  });
}

function sameStat(left, right) {
  return Object.keys(left).every((key) => left[key] === right[key]);
}

async function createArtifactSnapshot(sourcePath, expectedExtension, dependencies = {}) {
  const originalPath = resolve(sourcePath || '');
  const extension = String(expectedExtension || '').toLowerCase();
  if (!extension.startsWith('.') || extname(originalPath).toLowerCase() !== extension) {
    throw new Error(`Android verification artifact must use the ${extension || 'required'} extension.`);
  }

  const hashFile = dependencies.sha256File || sha256File;
  const before = stableStat(originalPath, 'Android verification source artifact');
  const sourceHashBefore = await hashFile(originalPath);
  const snapshotDirectory = mkdtempSync(join(tmpdir(), 'gc-android-verifier-'));
  const snapshotPath = join(snapshotDirectory, `${randomUUID()}${extension}`);
  let cleaned = false;

  try {
    copyFileSync(originalPath, snapshotPath, COPYFILE_EXCL);
    const snapshotStat = stableStat(snapshotPath, 'Verifier-owned Android artifact snapshot');
    const snapshotHash = await hashFile(snapshotPath);
    const after = stableStat(originalPath, 'Android verification source artifact');
    const sourceHashAfter = await hashFile(originalPath);
    if (
      !sameStat(before, after)
      || before.size !== snapshotStat.size
      || sourceHashBefore !== snapshotHash
      || sourceHashAfter !== snapshotHash
    ) {
      throw new Error('Android verification source artifact changed while it was being snapshotted.');
    }

    async function assertStable() {
      const currentStat = stableStat(snapshotPath, 'Verifier-owned Android artifact snapshot');
      const currentHash = await hashFile(snapshotPath);
      if (!sameStat(snapshotStat, currentStat) || currentHash !== snapshotHash) {
        throw new Error('Verifier-owned Android artifact snapshot changed during verification.');
      }
    }

    function cleanup() {
      if (!cleaned) {
        cleaned = true;
        rmSync(snapshotDirectory, { recursive: true, force: true });
      }
    }

    return Object.freeze({
      artifactBytes: snapshotStat.size,
      artifactSha256: snapshotHash,
      assertStable,
      cleanup,
      originalFile: basename(originalPath),
      originalPath,
      snapshotPath,
    });
  } catch (error) {
    rmSync(snapshotDirectory, { recursive: true, force: true });
    throw error;
  }
}

module.exports = {
  createArtifactSnapshot,
  sha256File,
};
