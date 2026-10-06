/** Apply locked upstream security fixes to npm's bundled dependencies only. */
import { cpSync, lstatSync, readFileSync, readdirSync, realpathSync, rmSync } from 'node:fs';
import { dirname, isAbsolute, join, relative, resolve, sep } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

const patchDirectory = resolve(dirname(fileURLToPath(import.meta.url)), '../tooling/npm-security');
const readJson = (path) => JSON.parse(readFileSync(path, 'utf8'));

function childPath(root, path) {
  const rel = relative(root, path);
  if (!rel || isAbsolute(rel) || rel === '..' || rel.startsWith(`..${sep}`)) {
    throw new Error('Toolchain replacement escapes the npm directory');
  }
  if (realpathSync(path) !== resolve(path) || lstatSync(path).isSymbolicLink()) {
    throw new Error('Toolchain package aliases are not permitted');
  }
}

function rejectPackageAliases(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.isSymbolicLink()) throw new Error('Toolchain package aliases are not permitted');
    if (entry.isDirectory()) rejectPackageAliases(join(directory, entry.name));
  }
}

export function replacementPlan(npmDirectory, sourceDirectory = patchDirectory) {
  const root = realpathSync(npmDirectory);
  const npm = readJson(join(root, 'package.json'));
  if (npm.name !== 'npm' || npm.version !== '11.20.0') {
    throw new Error('Security patches require the reviewed npm 11.20.0 distribution');
  }
  const lock = readJson(join(sourceDirectory, 'package-lock.json'));
  if (Object.keys(lock.packages).some((path) => path !== '' && !path.startsWith('node_modules/'))) {
    throw new Error('Unexpected npm security patch dependency closure');
  }
  const packages = new Map(Object.entries(lock.packages)
    .filter(([path]) => path.startsWith('node_modules/'))
    .map(([path, metadata]) => [path.slice('node_modules/'.length), metadata.version]));
  if ([...packages.keys()].sort().join(',') !== 'balanced-match,brace-expansion,http-cache-semantics,ip-address,undici') {
    throw new Error('Unexpected npm security patch dependency closure');
  }
  const found = new Set();
  const plan = [];
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (entry.name === '.bin') continue;
      const target = join(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error('Unexpected alias in bundled npm dependencies');
      if (!entry.isDirectory()) continue;
      if (packages.has(entry.name)) {
        childPath(root, target);
        const current = readJson(join(target, 'package.json'));
        const source = join(sourceDirectory, 'node_modules', entry.name);
        childPath(realpathSync(sourceDirectory), source);
        rejectPackageAliases(source);
        const replacement = readJson(join(source, 'package.json'));
        if (current.name !== entry.name || replacement.name !== entry.name || replacement.version !== packages.get(entry.name)) {
          throw new Error('Installed patch differs from its locked package identity');
        }
        found.add(entry.name);
        plan.push({ name: entry.name, version: replacement.version, source, target });
      }
      visit(target);
    }
  }
  visit(join(root, 'node_modules'));
  if (found.size !== packages.size) throw new Error('Expected bundled npm dependency was not found');
  return plan;
}

export function applyPatches(npmDirectory) {
  const root = realpathSync(npmDirectory);
  const metadata = readJson(join(root, 'package.json'));
  if (metadata.name !== 'npm' || metadata.version !== '11.20.0') {
    throw new Error('Security patches require the reviewed npm 11.20.0 distribution');
  }
  const result = spawnSync(process.execPath, [join(root, 'bin/npm-cli.js'), 'ci',
    '--prefix', patchDirectory, '--ignore-scripts', '--no-audit', '--no-fund',
    '--registry=https://registry.npmjs.org'], { stdio: 'inherit' });
  if (result.error || result.status !== 0) throw new Error('Installing integrity-locked npm security patches failed');
  const plan = replacementPlan(root);
  // Validate the complete plan before changing anything. All targets are inspected
  // existing package directories strictly inside this explicitly selected npm.
  for (const item of plan) {
    childPath(root, item.target);
    rmSync(item.target, { recursive: true });
    cpSync(item.source, item.target, { recursive: true, errorOnExist: true, force: false });
  }
  replacementPlan(root);
  console.log(`Applied ${plan.length} integrity-locked upstream security patches to npm 11.20.0`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv.length !== 3) throw new Error('Usage: node scripts/patch-npm-toolchain.mjs <installed-npm-directory>');
  applyPatches(process.argv[2]);
}
