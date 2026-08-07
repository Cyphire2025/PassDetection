import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const groupList = readFileSync(new URL("./document-group-list.tsx", import.meta.url), "utf8");
const hooks = readFileSync(new URL("../hooks/use-document-distribution.ts", import.meta.url), "utf8");
const api = readFileSync(new URL("../api/document-distribution.api.ts", import.meta.url), "utf8");

test("group selection search includes passenger names through a scoped server query", () => {
  assert.match(groupList, /Search by group, destination, or passenger/);
  assert.match(groupList, /useDocumentGroupSearch/);
  assert.match(groupList, /groupSearch\.data/);
  assert.match(hooks, /groupSearch: \(search: string\)/);
  assert.match(hooks, /listGroups\(normalizedSearch, signal\)/);
  assert.match(api, /params: search\?\.trim\(\) \? \{ search: search\.trim\(\) \}/);
});
