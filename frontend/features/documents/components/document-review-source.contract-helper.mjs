import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

export function readDocumentReviewSource() {
  const read = name => readFileSync(new URL(`./${name}.tsx`, import.meta.url), "utf8");
  const facade = read("document-workspace-review");
  const owners = [
    ["VerificationPanel", "document-verification-panel"],
    ["DocumentRowActionMenu", "document-row-action-menu"],
    ["DocumentSentStatus, MatchBadge", "document-review-badges"],
  ];
  for (const [names, file] of owners) {
    assert.ok(facade.includes(`export { ${names} } from "./${file}";`));
  }
  return [facade, ...owners.map(([, file]) => read(file))].join("\n");
}
