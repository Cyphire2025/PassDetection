import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { buildOfflineScanner, checkOfflineScannerArtifact } from "../../../scripts/build-offline-scanner.mjs";

test("the checked-in classic scanner is deterministic and source-bound", async () => {
  const first = await checkOfflineScannerArtifact();
  const second = await buildOfflineScanner();
  assert.equal(first.code, second.code);
  assert.equal(first.provenance, second.provenance);
  assert.doesNotMatch(first.code, /[A-Z]:\\|sourceMappingURL|\bfetch\s*\(|\bimport\s*\(/);
  assert.match(first.code, /^\/\*[\s\S]*GENERATED/);
  assert.ok(first.sources.length > 1);
});

test("artifact verification rejects a stale artifact and accepts checkout CRLF", async () => {
  const directory = await mkdtemp(join(tmpdir(), "offline-scanner-artifact-"));
  try {
    const { code } = await buildOfflineScanner();
    const path = join(directory, "scanner.js");
    await writeFile(path, code.replaceAll("\n", "\r\n"));
    await checkOfflineScannerArtifact(path);
    await writeFile(path, code.replace("Camera ready.", "Stale camera ready."));
    await assert.rejects(checkOfflineScannerArtifact(path), /artifact is stale/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("source binding is portable across roots and line endings and rejects stale authored source", async () => {
  const directory = await mkdtemp(join(tmpdir(), "offline-scanner-source-"));
  try {
    const first = await buildOfflineScanner();
    const ownerDirectory = join(directory, "features/tour-operations/offline-runtime");
    await mkdir(ownerDirectory, { recursive: true });
    for (const [name] of first.sources) {
      const value = await readFile(new URL(`../offline-runtime/${name}`, import.meta.url), "utf8");
      await writeFile(join(ownerDirectory, name), value.replaceAll("\r\n", "\n").replaceAll("\n", "\r\n"));
    }
    const options = { frontendDirectory: directory };
    const portable = await buildOfflineScanner(options);
    assert.equal(portable.code, first.code);
    const artifactPath = join(directory, "scanner.js");
    await writeFile(artifactPath, first.code);
    const constantPath = join(ownerDirectory, "constants.js");
    await writeFile(constantPath, `${await readFile(constantPath, "utf8")}\n// Synthetic changed source.\n`);
    await assert.rejects(checkOfflineScannerArtifact(artifactPath, options), /artifact is stale/);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test("the current Docker build reaches the stale-artifact check with pinned dev tooling", async () => {
  const pkg = JSON.parse(await readFile(new URL("../../../package.json", import.meta.url), "utf8"));
  const docker = await readFile(new URL("../../../Dockerfile", import.meta.url), "utf8");
  assert.match(pkg.scripts.prebuild, /^node scripts\/build-offline-scanner\.mjs --check && /);
  assert.match(docker, /FROM base AS deps[\s\S]*?RUN npm ci[\s\S]*?FROM base AS builder[\s\S]*?COPY --from=deps \/app\/node_modules[\s\S]*?RUN npm run build/);
  assert.doesNotMatch(docker.slice(0, docker.indexOf("FROM base AS runtime")), /NODE_ENV=production|npm ci --omit=dev/);
});
