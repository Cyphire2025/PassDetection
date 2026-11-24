import { createHash } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build, version as viteVersion } from "vite";

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const artifact = join(frontend, "public/offline-scanner.js");
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

/** Build one classic script. Authored modules are never public runtime assets. */
export async function buildOfflineScanner({ frontendDirectory = frontend } = {}) {
  const authoredDirectory = join(frontendDirectory, "features/tour-operations/offline-runtime");
  const names = (await readdir(authoredDirectory)).filter((name) => name.endsWith(".js")).sort();
  const sources = await Promise.all(names.map(async (name) => [
    name, sha256((await readFile(join(authoredDirectory, name), "utf8")).replaceAll("\r\n", "\n")),
  ]));
  const provenance = sha256(JSON.stringify({ viteVersion, sources }));
  const result = await build({
    root: frontendDirectory,
    configFile: false,
    envDir: false,
    publicDir: false,
    logLevel: "silent",
    build: {
      target: "es2022",
      minify: false,
      sourcemap: false,
      write: false,
      emptyOutDir: false,
      copyPublicDir: false,
      modulePreload: false,
      lib: {
        entry: join(authoredDirectory, "index.js"),
        formats: ["iife"],
        name: "OfflineCoordinatorScanner",
        fileName: () => "offline-scanner.js",
      },
    },
  });
  const outputs = (Array.isArray(result) ? result : [result]).flatMap((item) => (
    "output" in item ? item.output : []
  ));
  if (outputs.length !== 1) {
    throw new Error("The offline scanner must emit exactly one classic script.");
  }
  const chunk = outputs[0];
  if (chunk.type !== "chunk" || chunk.imports.length || chunk.dynamicImports.length) {
    throw new Error("The offline scanner must not load additional runtime assets.");
  }
  // Rolldown's region labels are relative to the invoking process directory.
  // Canonicalize only those generated comments, retaining useful owner names.
  const script = chunk.code.replaceAll("\r\n", "\n").replace(
    /^([\t ]*\/\/#region ).*[/\\]offline-runtime[/\\]([a-z-]+\.js)$/gm,
    "$1features/tour-operations/offline-runtime/$2",
  );
  const code = `/*
 * GENERATED from features/tour-operations/offline-runtime/*.js; do not edit.
 * Regenerate: node scripts/build-offline-scanner.mjs --write
 * Vite ${viteVersion}; authored source SHA-256: ${provenance}
 *
 * QR decoding uses the exact @zxing/browser 0.2.0 UMD distribution vendored at
 * /offline/vendor/zxing-browser.min.js. It is MIT licensed; the upstream
 * license is preserved at /offline/vendor/zxing-browser.LICENSE.txt.
 */
${script}`;
  return { code, provenance, sources, viteVersion };
}

export async function checkOfflineScannerArtifact(path = artifact, options) {
  const generated = await buildOfflineScanner(options);
  if ((await readFile(path, "utf8")).replaceAll("\r\n", "\n") !== generated.code) {
    throw new Error("Offline scanner artifact is stale. Run node scripts/build-offline-scanner.mjs --write and review the generated change.");
  }
  return generated;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [mode, ...extra] = process.argv.slice(2);
  if (extra.length || !["--check", "--write"].includes(mode)) {
    throw new Error("Usage: node scripts/build-offline-scanner.mjs --check|--write");
  }
  const generated = mode === "--check"
    ? await checkOfflineScannerArtifact()
    : await buildOfflineScanner();
  if (mode === "--write") await writeFile(artifact, generated.code, "utf8");
  process.stdout.write(`Offline scanner ${mode === "--check" ? "verified" : "generated"}: ${generated.provenance}\n`);
}
