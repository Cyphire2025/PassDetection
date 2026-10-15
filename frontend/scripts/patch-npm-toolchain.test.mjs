import assert from 'node:assert/strict';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative, resolve } from 'node:path';
import test from 'node:test';
import { replacementPlan } from './patch-npm-toolchain.mjs';

const versions = {
  'balanced-match': '4.0.4',
  'brace-expansion': '5.0.12',
  'http-cache-semantics': '4.3.0',
  'ip-address': '10.7.1',
  undici: '6.29.0',
};

function json(path, value) {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(value));
}

function fixture(t) {
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'npm-patch-regression-'));
  const npm = join(root, 'npm');
  const source = join(root, 'patches');
  const lock = { lockfileVersion: 3, packages: { '': { name: 'fixture', version: '1.0.0' } } };
  const target = (name) => join(npm, 'node_modules', name);
  const replacement = (name) => join(source, 'node_modules', name);
  json(join(npm, 'package.json'), { name: 'npm', version: '11.20.0' });
  for (const [name, version] of Object.entries(versions)) {
    lock.packages[`node_modules/${name}`] = { version };
    json(join(target(name), 'package.json'), { name, version: '0.0.1' });
    json(join(replacement(name), 'package.json'), { name, version });
    writeFileSync(join(target(name), 'old.txt'), 'original package');
    writeFileSync(join(replacement(name), 'patched.txt'), 'replacement package');
  }
  const saveLock = () => json(join(source, 'package-lock.json'), lock);
  saveLock();
  // Only remove the freshly allocated fixture; linked escape targets also live here.
  t.after(() => {
    assert.equal(realpathSync(root), resolve(root));
    assert.equal(dirname(root), realpathSync(tmpdir()));
    rmSync(root, { recursive: true, force: true });
  });
  return { root, npm, source, lock, saveLock, target, replacement };
}

function rejectedWithoutMutation(f, expected) {
  assert.throws(() => replacementPlan(f.npm, f.source), expected);
  // Validation must not partially patch a package before finding a later error.
  assert.equal(readFileSync(join(f.target('balanced-match'), 'old.txt'), 'utf8'), 'original package');
  assert.equal(existsSync(join(f.target('balanced-match'), 'patched.txt')), false);
}

test('plans every reviewed replacement, preserves unrelated packages, and supports repeat application', (t) => {
  const f = fixture(t);
  const unrelated = join(f.npm, 'node_modules', 'unrelated');
  json(join(unrelated, 'package.json'), { name: 'unrelated', version: '1.0.0' });
  const plan = replacementPlan(f.npm, f.source);
  assert.equal(plan.length, 5);
  assert.deepEqual(Object.fromEntries(plan.map(({ name, version }) => [name, version])), versions);
  for (const item of plan) {
    assert.equal(item.target, f.target(item.name));
    assert.equal(item.source, f.replacement(item.name));
    assert.ok(!relative(f.npm, item.target).startsWith('..'));
    rmSync(item.target, { recursive: true });
    cpSync(item.source, item.target, { recursive: true, force: false, errorOnExist: true });
    assert.equal(existsSync(join(item.target, 'old.txt')), false);
    assert.equal(readFileSync(join(item.target, 'patched.txt'), 'utf8'), 'replacement package');
  }
  assert.deepEqual(replacementPlan(f.npm, f.source), plan);
  assert.equal(JSON.parse(readFileSync(join(unrelated, 'package.json'), 'utf8')).version, '1.0.0');
});

test('finds duplicate bundled dependencies nested under another npm dependency', (t) => {
  const f = fixture(t);
  const nested = join(f.npm, 'node_modules', 'parent', 'node_modules', 'undici');
  json(join(nested, 'package.json'), { name: 'undici', version: '6.27.0' });
  const plan = replacementPlan(f.npm, f.source);
  assert.equal(plan.length, 6);
  assert.deepEqual(plan.filter(({ name }) => name === 'undici').map(({ target }) => target).sort(), [f.target('undici'), nested].sort());
});

for (const metadata of [{ name: 'npm-alias', version: '11.20.0' }, { name: 'npm', version: '11.21.0' }]) {
  test(`rejects an unreviewed npm distribution: ${metadata.name}@${metadata.version}`, (t) => {
    const f = fixture(t);
    json(join(f.npm, 'package.json'), metadata);
    rejectedWithoutMutation(f, /reviewed npm 11\.20\.0/);
  });
}

for (const [label, change] of [
  ['installed package name alias', (f) => json(join(f.target('undici'), 'package.json'), { name: 'other-package', version: '6.27.0' })],
  ['replacement package name alias', (f) => json(join(f.replacement('undici'), 'package.json'), { name: 'other-package', version: versions.undici })],
  ['replacement version differing from the lock', (f) => json(join(f.replacement('undici'), 'package.json'), { name: 'undici', version: '99.0.0' })],
  ['lock version differing from the installed replacement', (f) => { f.lock.packages['node_modules/undici'].version = '99.0.0'; f.saveLock(); }],
]) {
  test(`rejects ${label} before changing any target`, (t) => {
    const f = fixture(t);
    change(f);
    rejectedWithoutMutation(f, /locked package identity/);
  });
}

for (const path of ['node_modules/unreviewed', 'node_modules/parent/node_modules/undici', 'node_modules/../undici', '../outside', 'packages/unreviewed']) {
  test(`rejects unexpected dependency closure entry ${path}`, (t) => {
    const f = fixture(t);
    f.lock.packages[path] = { version: '1.0.0' };
    f.saveLock();
    rejectedWithoutMutation(f, /dependency closure/);
  });
}

test('rejects an incomplete locked replacement closure', (t) => {
  const f = fixture(t);
  delete f.lock.packages['node_modules/undici'];
  f.saveLock();
  rejectedWithoutMutation(f, /dependency closure/);
});

test('rejects a reviewed package missing from the bundled npm tree', (t) => {
  const f = fixture(t);
  rmSync(f.target('undici'), { recursive: true });
  rejectedWithoutMutation(f, /bundled npm dependency was not found/);
});

for (const kind of ['target', 'replacement']) {
  test(`rejects a ${kind} directory alias escaping its allowed root`, (t) => {
    const f = fixture(t);
    const path = f[kind]('undici');
    const outside = join(f.root, `${kind}-outside`);
    json(join(outside, 'package.json'), { name: 'undici', version: versions.undici });
    writeFileSync(join(outside, 'keep.txt'), 'must remain untouched');
    rmSync(path, { recursive: true });
    symlinkSync(outside, path, process.platform === 'win32' ? 'junction' : 'dir');
    rejectedWithoutMutation(f, /aliases|alias/);
    assert.equal(readFileSync(join(outside, 'keep.txt'), 'utf8'), 'must remain untouched');
  });
}

test('rejects source aliases hidden inside package contents before they can be copied', (t) => {
  const f = fixture(t);
  const outside = join(f.root, 'outside-payload');
  mkdirSync(outside);
  writeFileSync(join(outside, 'keep.txt'), 'outside payload');
  symlinkSync(outside, join(f.replacement('undici'), 'lib'), process.platform === 'win32' ? 'junction' : 'dir');
  rejectedWithoutMutation(f, /aliases/);
  assert.equal(readFileSync(join(outside, 'keep.txt'), 'utf8'), 'outside payload');
});

test('rejects aliases hidden under an unrelated bundled package', (t) => {
  const f = fixture(t);
  const parent = join(f.npm, 'node_modules', 'unrelated');
  mkdirSync(parent);
  symlinkSync(f.source, join(parent, 'linked-tree'), process.platform === 'win32' ? 'junction' : 'dir');
  rejectedWithoutMutation(f, /alias/);
});
