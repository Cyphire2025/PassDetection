import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

const proxy = read("../proxy.ts");
const layout = read("./(legal)/layout.tsx");
const home = read("./(legal)/email-automation/page.tsx");
const privacy = read("./(legal)/privacy-policy/page.tsx");
const terms = read("./(legal)/terms/page.tsx");

test("legal pages remain public and link to each other", () => {
  assert.doesNotMatch(proxy, /"\/email-automation"/);
  assert.doesNotMatch(proxy, /"\/privacy-policy"/);
  assert.doesNotMatch(proxy, /"\/terms"/);
  assert.match(layout, /"\/privacy-policy"/);
  assert.match(layout, /"\/terms"/);
});

test("OAuth homepage explains both supported read-only mail providers", () => {
  assert.match(
    home,
    /const APP_NAME = "Global Connect Travels Email Automation"/,
  );
  assert.match(home, /title: \{ absolute: APP_NAME \}/);
  assert.match(home, /applicationName: APP_NAME/);
  assert.match(home, /canonical: APP_URL/);
  assert.match(home, /manifest: "\/email-automation\.webmanifest"/);
  assert.match(home, /identifies travel-related messages/);
  assert.match(home, /read-only Gmail access/);
  assert.match(home, /delegated read-only mail access/);
  assert.match(home, /does not send, edit, or delete/);
  assert.match(home, /https:\/\/tech\.gctravels\.com\/privacy-policy/);
  assert.match(home, /https:\/\/tech\.gctravels\.com\/terms/);
  assert.match(home, /available without signing/);
  assert.doesNotMatch(layout, /href="\/"/);
  assert.match(layout, /href=\{"\/email-automation" as never\}/);
});

test("privacy policy discloses Gmail and Outlook access and data controls", () => {
  assert.match(privacy, /Gmail message metadata/);
  assert.match(privacy, /Outlook\s+message metadata/);
  assert.match(privacy, /Google API Services User Data Policy/);
  assert.match(privacy, /Limited Use/);
  assert.match(privacy, /Retention and deletion/);
  assert.match(privacy, /disconnect a linked Google or Microsoft account/);
});

test("terms explain authorization and human review responsibilities", () => {
  assert.match(terms, /account holder grants permission/);
  assert.match(terms, /human review/);
  assert.match(terms, /Automated extraction/);
  assert.match(terms, /Acceptable use/);
});
