import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";

export const portraitUrl = "https://storage.googleapis.com/mediapipe-assets/portrait.jpg";
export const portraitSha256 = "a6f11efaa834706db23f275b6115058fa87fc7f14362681e6abe14e82749de3e";
/** One canonical public model fixture; never accept caller-supplied URLs or passenger images. */
export async function verifiedPortrait(frontend) {
  const directory = join(frontend, "../.tmp/browser-verification"), path = join(directory, "portrait.jpg");
  let bytes, downloaded = false;
  try { bytes = await readFile(path); }
  catch (error) {
    if (error.code !== "ENOENT") throw error;
    const response = await fetch(portraitUrl, { signal: AbortSignal.timeout(15_000), redirect: "error" });
    assert.equal(response.status, 200, "Canonical MediaPipe public fixture must be available");
    bytes = Buffer.from(await response.arrayBuffer()); downloaded = true;
  }
  assert.ok(bytes.length > 0 && bytes.length <= 2 * 1024 * 1024);
  assert.equal(createHash("sha256").update(bytes).digest("hex"), portraitSha256, "Unexpected canonical portrait revision");
  if (downloaded) {
    await mkdir(directory, { recursive: true }); await writeFile(path, bytes);
    await writeFile(join(directory, "portrait-provenance.json"), JSON.stringify({ url: portraitUrl, sha256: portraitSha256, bytes: bytes.length, acquired_at: new Date().toISOString(), scope: "Canonical public MediaPipe test fixture; no product/passenger data" }, null, 2));
  }
  return bytes;
}
