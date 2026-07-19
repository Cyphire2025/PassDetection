import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

test("root-page camera claims match manual Gemini-based production flows", () => {
  assert.match(source, /Mobile-first manual passport and Visa Photo capture/);
  assert.match(source, /Gemini-based passport field extraction/);
  assert.doesNotMatch(source, /auto[- ]?capture|hands-free/i);
  assert.doesNotMatch(source, /MRZ-only extraction/i);
});
