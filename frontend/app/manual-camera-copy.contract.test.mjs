import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

test("the hidden root page exposes no obsolete camera or extraction claims", () => {
  assert.match(source, /redirect\("\/login"\)/);
  assert.doesNotMatch(source, /Mobile-first manual passport and Visa Photo capture/);
  assert.doesNotMatch(source, /Gemini-based passport field extraction/);
  assert.doesNotMatch(source, /auto[- ]?capture|hands-free/i);
  assert.doesNotMatch(source, /MRZ-only extraction/i);
});
