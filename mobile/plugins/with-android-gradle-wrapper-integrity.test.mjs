import assert from 'node:assert/strict';
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  writeFile,
} from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  REVIEWED_GRADLE_DISTRIBUTION_SHA256,
} = require('../scripts/android-release-toolchain.js');
const {
  patchGradleWrapperProperties,
  writeReviewedGradleWrapper,
} = require('./with-android-gradle-wrapper-integrity.js');

const generatedWrapper = [
  'distributionBase=GRADLE_USER_HOME',
  'distributionUrl=https\\://services.gradle.org/distributions/gradle-9.3.1-bin.zip',
  'networkTimeout=10000',
  '',
].join('\n');

test('clean Expo prebuild output receives the reviewed Gradle distribution checksum', () => {
  const patched = patchGradleWrapperProperties(generatedWrapper);
  assert.match(
    patched,
    new RegExp(`^distributionSha256Sum=${REVIEWED_GRADLE_DISTRIBUTION_SHA256}$`, 'm'),
  );
  assert.equal(patchGradleWrapperProperties(patched), patched);
});

test('the prebuild mod writes and revalidates the generated wrapper file', async (context) => {
  const platformProjectRoot = await mkdtemp(join(tmpdir(), 'gc-gradle-wrapper-'));
  context.after(() => rm(platformProjectRoot, { force: true, recursive: true }));
  const wrapperDirectory = join(platformProjectRoot, 'gradle', 'wrapper');
  const wrapperPath = join(wrapperDirectory, 'gradle-wrapper.properties');
  await mkdir(wrapperDirectory, { recursive: true });
  await writeFile(wrapperPath, generatedWrapper, 'utf8');

  await writeReviewedGradleWrapper(platformProjectRoot);

  assert.match(
    await readFile(wrapperPath, 'utf8'),
    new RegExp(`^distributionSha256Sum=${REVIEWED_GRADLE_DISTRIBUTION_SHA256}$`, 'm'),
  );
});

test('Gradle wrapper generation fails closed on version or checksum drift', () => {
  assert.throws(
    () => patchGradleWrapperProperties(
      generatedWrapper.replace('gradle-9.3.1-bin.zip', 'gradle-9.4.1-bin.zip'),
    ),
    /must use reviewed Gradle 9\.3\.1/,
  );
  assert.throws(
    () => patchGradleWrapperProperties(
      `${generatedWrapper}distributionSha256Sum=${'0'.repeat(64)}\n`,
    ),
    /distribution checksum is invalid/,
  );
  assert.throws(
    () => patchGradleWrapperProperties(
      `${generatedWrapper}distributionSha256Sum=${REVIEWED_GRADLE_DISTRIBUTION_SHA256}\n`
      + `distributionSha256Sum=${REVIEWED_GRADLE_DISTRIBUTION_SHA256}\n`,
    ),
    /must not declare duplicate distribution checksums/,
  );
});
