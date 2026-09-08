const fs = require('node:fs/promises');
const path = require('node:path');

const { withDangerousMod } = require('@expo/config-plugins');

const HEADLESS_MARKER = '# Preserve Expo headless app loader reflection targets.';
const GL_MARKER = '# Preserve Expo GLView constructor used by the reflective Expo view factory.';
const GL_CONSTRUCTOR_RULE = `-keep class expo.modules.gl.GLView {
  public <init>(android.content.Context, expo.modules.kotlin.AppContext);
}`;
const GL_FLUSH_MARKER = '# Preserve the GLContext callback resolved by name in EXGLJniApi.cpp.';
const GL_FLUSH_RULE = `-keepclassmembers class expo.modules.gl.GLContext {
  public void flush();
}`;
const GL_NATIVE_MARKER = '# Preserve Expo GL JNI export class and native method names.';
const GL_NATIVE_RULE = `-keep class expo.modules.gl.cpp.EXGL {
  public static native <methods>;
}`;
const RULES = [
  [HEADLESS_MARKER, '-keep class expo.modules.adapters.react.apploader.** { *; }'],
  [GL_MARKER, GL_CONSTRUCTOR_RULE],
  [GL_FLUSH_MARKER, GL_FLUSH_RULE],
  [GL_NATIVE_MARKER, GL_NATIVE_RULE],
];

function patchExpoReflectionKeepRules(source) {
  const newline = source.includes('\r\n') ? '\r\n' : '\n';
  let patched = source;
  for (const [marker, rule] of RULES) {
    // An older generated project already contains the headless marker. Check
    // every rule independently so later reflection fixes still reach that build.
    if (patched.replaceAll('\r\n', '\n').includes(rule)) continue;
    const separator = patched.endsWith('\n') ? newline : `${newline}${newline}`;
    const comment = patched.includes(marker) ? '' : `${marker}${newline}`;
    patched += `${separator}${comment}${rule.replaceAll('\n', newline)}${newline}`;
  }
  return patched;
}

async function writeExpoReflectionKeepRules(platformProjectRoot) {
  const rulesPath = path.join(platformProjectRoot, 'app', 'proguard-rules.pro');
  const current = await fs.readFile(rulesPath, 'utf8');
  const patched = patchExpoReflectionKeepRules(current);
  if (patched !== current) await fs.writeFile(rulesPath, patched, 'utf8');
}

/**
 * Expo resolves RNHeadlessAppLoader by class name. R8 cannot discover that
 * reflective edge, so release minification needs an explicit keep rule.
 * Expo GL 57's GLView extends TextureView instead of implementing ExpoView, so
 * Expo core's constructor keep rule misses it. ViewDefinitionBuilder resolves
 * its (Context, AppContext) constructor reflectively. Preserve only that class
 * and constructor; ordinary GL implementation members remain optimizable.
 * EXGLJniApi.cpp also uses GetMethodID("flush", "()V") on a GLContext instance.
 * Unlike native declarations, that Java callback is invisible to the default
 * Android native-method keep rules. Its name and body must both survive R8.
 * The explicit EXGL rule preserves the class/method names encoded in JNI exports.
 */
module.exports = function withExpoHeadlessLoaderProguard(config) {
  return withDangerousMod(config, [
    'android',
    async (dangerousConfig) => {
      await writeExpoReflectionKeepRules(dangerousConfig.modRequest.platformProjectRoot);
      return dangerousConfig;
    },
  ]);
};

module.exports.patchExpoReflectionKeepRules = patchExpoReflectionKeepRules;
module.exports.writeExpoReflectionKeepRules = writeExpoReflectionKeepRules;
