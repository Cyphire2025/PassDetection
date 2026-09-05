import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspace = readFileSync(new URL("./document-workspace.tsx", import.meta.url), "utf8");
const review = readFileSync(new URL("./document-workspace-review.tsx", import.meta.url), "utf8");

test("the review table preserves readable columns inside a keyboard-accessible horizontal scroller", () => {
  const tableMinimum = workspace.match(/<table\s+className="[^"]*min-w-\[(\d+)px\]/);
  assert.ok(tableMinimum, "The seven-column document table needs an explicit minimum width");
  assert.ok(Number(tableMinimum[1]) >= 1_000, "Mobile must scroll the roster rather than squeeze its columns");
  assert.match(
    workspace,
    /className="[^"]*overflow-x-auto[^"]*overscroll-x-contain"\s+role="region"\s+aria-label="Passenger document review table"\s+tabIndex=\{0\}/,
  );
});

test("document row actions escape the table clipping boundary and retain viewport bounds", () => {
  assert.match(review, /open && createPortal\(/);
  assert.match(review, /document\.body/);
  assert.match(review, /role="menu"[^>]*className="fixed [^"]*max-w-\[calc\(100vw-16px\)\][^"]*overflow-y-auto/);
  for (const event of ["scroll", "resize"]) {
    assert.match(review, new RegExp(`window\\.addEventListener\\("${event}", closeOnMove`));
    assert.match(review, new RegExp(`window\\.removeEventListener\\("${event}", closeOnMove`));
  }
});
