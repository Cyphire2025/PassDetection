import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("./document-rename-page.tsx", import.meta.url), "utf8");

test("all-rejected rename batches do not expose empty ZIP downloads", () => {
  assert.match(page, /batch\.visa_count \+ batch\.ticket_count > 0/);
  assert.match(page, /const hasDownloadableDocuments =/);
  assert.match(page, /hasDownloadableDocuments \?/);
  assert.match(page, /No verified PDFs to download/);
});

test("rename ZIP opens safely only after the logical upload completes", () => {
  assert.match(page, /batch\.status === "completed"/);
  assert.match(page, /Upload incomplete/);
  assert.match(page, /target="_blank" rel="noopener noreferrer"/);
});

test("same-page retries keep the immutable title bound to the upload session", () => {
  assert.match(page, /const \[uploadSessionTitle, setUploadSessionTitle\]/);
  assert.match(page, /title: activeTitle \?\? title\.trim\(\)/);
  assert.match(page, /disabled=\{analyze\.isPending \|\| uploadSession !== null\}/);
});
