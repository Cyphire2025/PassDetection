import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const layout = readFileSync(
  new URL("./(dashboard)/layout.tsx", import.meta.url),
  "utf8",
);
const globals = readFileSync(new URL("./globals.css", import.meta.url), "utf8");

test("dashboard shell remains anchored while only main content scrolls", () => {
  assert.match(layout, /className="fixed inset-0 flex min-h-0/);
  assert.match(layout, /data-dashboard-shell/);
  assert.match(
    layout,
    /className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-y-contain"/,
  );
  assert.doesNotMatch(layout, /h-\[100svh\]/);
});

test("dashboard routes lock the root document scroller", () => {
  assert.match(globals, /html:has\(\[data-dashboard-shell\]\)/);
  assert.match(globals, /body:has\(\[data-dashboard-shell\]\)/);
  assert.match(
    globals,
    /body:has\(\[data-dashboard-shell\]\)\s*\{[\s\S]*?overflow: hidden;[\s\S]*?overscroll-behavior: none;/,
  );
});
