import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panelSource = readFileSync(
  new URL("./managed-accounts-panel.tsx", import.meta.url),
  "utf8",
);
const hookSource = readFileSync(
  new URL("../hooks/use-operations.ts", import.meta.url),
  "utf8",
);

test("staff group choices are limited to the staff agency and non-removed groups", () => {
  assert.match(panelSource, /group\.agency_id === staff\.agency_id/);
  assert.match(panelSource, /group\.status !== "archived"/);
  assert.match(panelSource, /group\.status !== "deleted"/);
});

test("staff access assignment reports failures and updates the account cache", () => {
  assert.match(panelSource, /assignStaffGroups\.mutateAsync/);
  assert.match(panelSource, /role="alert"/);
  assert.match(hookSource, /setQueryData<StaffAccount\[\]>/);
});
