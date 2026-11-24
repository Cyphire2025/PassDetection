import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = name => readFileSync(new URL(`../api/${name}`, import.meta.url), "utf8");
const owners = [
  ["document-review.api.ts", "documentReviewApi"],
  ["document-verification.api.ts", "documentVerificationApi"],
  ["document-batches.api.ts", "documentBatchesApi"],
  ["document-delivery.api.ts", "documentDeliveryApi"],
];

/** Follow the actual ordered facade owners before inspecting their contracts. */
export function readDocumentDistributionSource() {
  const facade = read("document-distribution.api.ts");
  for (const [file, binding] of owners) {
    assert.ok(facade.includes(`import { ${binding} } from "./${file.slice(0, -3)}"`), `${file} import is wired`);
    assert.ok(facade.includes(`...${binding},`), `${binding} is exposed by the facade`);
  }
  return [...owners.map(([file]) => read(file)), read("document-distribution.types.ts")].join("\n");
}
