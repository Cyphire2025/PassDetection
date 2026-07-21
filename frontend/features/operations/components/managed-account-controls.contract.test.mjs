import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("./managed-account-controls.tsx", import.meta.url),
  "utf8",
);

test("account actions remain mounted when a menu item is clicked", () => {
  assert.match(source, /const menuRef = useRef<HTMLDivElement \| null>\(null\)/);
  assert.match(
    source,
    /buttonRef\.current\?\.contains\(target\) \|\| menuRef\.current\?\.contains\(target\)/,
  );
  assert.match(source, /ref=\{menuRef\}/);
});

test("staff deletion reports backend failures instead of failing silently", () => {
  assert.match(source, /actions\.deleteAccount\.mutateAsync\(accountId\)/);
  assert.match(source, /setActionError\(getAccountActionError\(deleteError\)\)/);
  assert.match(source, /role="alert"/);
});
