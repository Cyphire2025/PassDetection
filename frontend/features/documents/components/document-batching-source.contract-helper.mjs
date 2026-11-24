import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

export function readDocumentBatchingSource() {
  const read = name => readFileSync(new URL(`../services/${name}.ts`, import.meta.url), "utf8");
  const facade = read("document-upload-batching");
  const owners = [
    "document-upload-model",
    "document-upload-sessions",
    "document-verification-batches",
    "document-staging-manifest",
    "document-upload-finalization",
  ];
  for (const owner of owners) {
    assert.match(facade, new RegExp(`from "\\./${owner}\\.ts"`));
  }
  const retry = read("document-upload-retry");
  const verification = read("document-verification-batches");
  const finalization = read("document-upload-finalization");
  for (const source of [verification, finalization]) {
    assert.match(source, /import \{ retryTransientDocumentChunk \} from "\.\/document-upload-retry\.ts"/);
    assert.match(source, /await retryTransientDocumentChunk\(/);
  }
  return [facade, ...owners.map(read), retry].join("\n");
}
