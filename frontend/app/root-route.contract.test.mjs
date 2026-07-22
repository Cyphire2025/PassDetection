import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const rootPage = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");

test("the public domain root redirects to login without rendering product internals", () => {
  assert.match(rootPage, /redirect\("\/login"\)/);
  assert.doesNotMatch(rootPage, /Enter Platform/);
  assert.doesNotMatch(rootPage, /Phases 1 through/);
  assert.doesNotMatch(rootPage, /Enterprise Passport MRZ Platform/);
});
