import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

/** Read only modules reachable from the scanner's real authored entry. */
export function readOfflineRuntimeSource() {
  const directory = new URL("../offline-runtime/", import.meta.url);
  const seen = new Set();
  function read(name) {
    assert.match(name, /^\.\/[a-z-]+\.js$/);
    if (seen.has(name)) return "";
    seen.add(name);
    const source = readFileSync(new URL(name, directory), "utf8");
    const dependencies = [...source.matchAll(/from ['"](.+?)['"]/g)].map((match) => match[1]);
    return [source, ...dependencies.map(read)].join("\n");
  }
  return read("./index.js");
}
