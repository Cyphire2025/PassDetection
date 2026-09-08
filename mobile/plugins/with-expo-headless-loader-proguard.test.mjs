import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const require = createRequire(import.meta.url);
const { patchExpoReflectionKeepRules, writeExpoReflectionKeepRules } = require('./with-expo-headless-loader-proguard.js');
const HEADLESS_RULE = '-keep class expo.modules.adapters.react.apploader.** { *; }';
const GL_RULE = /-keep class expo\.modules\.gl\.GLView \{\n  public <init>\(android\.content\.Context, expo\.modules\.kotlin\.AppContext\);\n\}/;
const FLUSH_RULE = /-keepclassmembers class expo\.modules\.gl\.GLContext \{\n  public void flush\(\);\n\}/;
const NATIVE_RULE = /-keep class expo\.modules\.gl\.cpp\.EXGL \{\n  public static native <methods>;\n\}/;
const previousGeneratedRules = `# App rules\n-keep class example.Existing { *; }\n\n# Preserve Expo headless app loader reflection targets.\n${HEADLESS_RULE}\n`;

test('fresh prebuild receives both reflection targets without preserving the whole GL package', () => {
  const patched = patchExpoReflectionKeepRules('# App rules\n');
  assert.ok(patched.includes(HEADLESS_RULE));
  assert.match(patched, GL_RULE);
  assert.match(patched, FLUSH_RULE);
  assert.match(patched, NATIVE_RULE);
  assert.doesNotMatch(patched, /expo\.modules\.gl\.\*|expo\.modules\.\*\*/);
  assert.equal(patchExpoReflectionKeepRules(patched), patched);
});

test('an existing headless marker does not suppress the new GL constructor fix', () => {
  const patched = patchExpoReflectionKeepRules(previousGeneratedRules);
  assert.ok(patched.startsWith(previousGeneratedRules));
  assert.match(patched, GL_RULE);
  assert.equal(patched.split(HEADLESS_RULE).length - 1, 1);
  assert.equal(patchExpoReflectionKeepRules(patched), patched);
});

test('the previously generated constructor-only fix is upgraded with all native bridge rules', () => {
  const constructorOnly = `${previousGeneratedRules}# Preserve Expo GLView constructor used by the reflective Expo view factory.\n`
    + '-keep class expo.modules.gl.GLView {\n  public <init>(android.content.Context, expo.modules.kotlin.AppContext);\n}\n';
  const patched = patchExpoReflectionKeepRules(constructorOnly);
  assert.ok(patched.startsWith(constructorOnly));
  assert.match(patched, FLUSH_RULE);
  assert.match(patched, NATIVE_RULE);
  assert.equal(patched.split('-keep class expo.modules.gl.GLView').length - 1, 1);
  assert.equal(patchExpoReflectionKeepRules(patched), patched);
});

test('missing rule after an existing GL comment is repaired and Windows newlines are preserved', () => {
  const source = `${previousGeneratedRules}# Preserve Expo GLView constructor used by the reflective Expo view factory.\n`
    .replaceAll('\n', '\r\n');
  const patched = patchExpoReflectionKeepRules(source);
  assert.match(patched.replaceAll('\r\n', '\n'), GL_RULE);
  assert.equal(patched.split('# Preserve Expo GLView constructor').length - 1, 1);
  assert.doesNotMatch(patched, /(?<!\r)\n/);
  assert.equal(patchExpoReflectionKeepRules(patched), patched);
});

test('native rule writer upgrades the exact generated file without changing unrelated rules', async (context) => {
  const platformRoot = await mkdtemp(join(tmpdir(), 'gc-expo-reflection-'));
  context.after(async () => {
    const absolute = resolve(platformRoot);
    assert.ok(absolute.startsWith(`${resolve(tmpdir())}${sep}gc-expo-reflection-`));
    await rm(absolute, { force: true, recursive: true });
  });
  const rulesPath = join(platformRoot, 'app', 'proguard-rules.pro');
  await mkdir(join(platformRoot, 'app'));
  await writeFile(rulesPath, previousGeneratedRules, 'utf8');
  await writeExpoReflectionKeepRules(platformRoot);
  const patched = await readFile(rulesPath, 'utf8');
  assert.ok(patched.startsWith(previousGeneratedRules));
  assert.match(patched, GL_RULE);
  assert.match(patched, FLUSH_RULE);
  assert.match(patched, NATIVE_RULE);
  await writeExpoReflectionKeepRules(platformRoot);
  assert.equal(await readFile(rulesPath, 'utf8'), patched);
});

test('reviewed Expo GL native sources have no unprotected named Java lookup', async () => {
  const glRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../node_modules/expo-gl');
  async function nativeSources(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    const nested = await Promise.all(entries.map(async (entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) return nativeSources(path);
      return /\.(?:c|cc|cpp|h|hpp)$/.test(entry.name) ? [await readFile(path, 'utf8')] : [];
    }));
    return nested.flat();
  }
  const sources = (await Promise.all([
    nativeSources(join(glRoot, 'android/src/main/cpp')), nativeSources(join(glRoot, 'common')),
  ])).flat().join('\n');
  const lookups = [...sources.matchAll(/->(Get(?:Static)?(?:Method|Field)ID|FindClass|RegisterNatives)\s*\(([^;]+)\)/g)]
    .map((match) => ({ operation: match[1], arguments: match[2].replace(/\s+/g, '') }));
  // Any new JNI reflection edge on an Expo update needs an explicit keep-rule
  // review, rather than another release-only startup failure.
  assert.deepEqual(lookups, [{ operation: 'GetMethodID', arguments: 'GLContextClass,"flush","()V"' }]);
  const javaContext = await readFile(join(glRoot, 'android/src/main/java/expo/modules/gl/GLContext.java'), 'utf8');
  assert.match(javaContext, /public void flush\(\)/);
  assert.match(patchExpoReflectionKeepRules(''), FLUSH_RULE);

  const javaEntry = await readFile(join(glRoot, 'android/src/main/java/expo/modules/gl/cpp/EXGL.java'), 'utf8');
  const declared = [...javaEntry.matchAll(/public static native \w+ (\w+)\(/g)].map((match) => match[1]).sort();
  const exported = [...sources.matchAll(/Java_expo_modules_gl_cpp_EXGL_(\w+)\s*\(/g)].map((match) => match[1]).sort();
  assert.equal(declared.length, 12, 'Review Expo GL JNI bridge changes when upgrading dependencies.');
  assert.deepEqual(exported, declared);
  assert.match(patchExpoReflectionKeepRules(''), NATIVE_RULE);
});
