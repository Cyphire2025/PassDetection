import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

const proxy = read("../proxy.ts");
const layout = read("./(legal)/layout.tsx");
const privacy = read("./(legal)/privacy-policy/page.tsx");
const terms = read("./(legal)/terms/page.tsx");

test("legal pages remain public and link to each other", () => {
  assert.doesNotMatch(proxy, /"\/privacy-policy"/);
  assert.doesNotMatch(proxy, /"\/terms"/);
  assert.match(layout, /"\/privacy-policy"/);
  assert.match(layout, /"\/terms"/);
});

test("privacy policy discloses Gmail access and data controls", () => {
  assert.match(privacy, /Gmail message metadata/);
  assert.match(privacy, /Google API Services User Data Policy/);
  assert.match(privacy, /Limited Use/);
  assert.match(privacy, /Retention and deletion/);
  assert.match(privacy, /disconnect a linked Google account/);
});

test("terms explain authorization and human review responsibilities", () => {
  assert.match(terms, /account holder grants permission/);
  assert.match(terms, /human review/);
  assert.match(terms, /Automated extraction/);
  assert.match(terms, /Acceptable use/);
});
