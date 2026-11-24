import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

export function readDocumentRenameSource() {
  const read = path => readFileSync(new URL(path, import.meta.url), "utf8");
  const page = read("./document-rename-page.tsx");
  const owners = [
    ["DocumentRenameUpload", "document-rename-upload"],
    ["SavedRenameBatches", "saved-rename-batches"],
    ["RenameResults", "rename-results"],
  ];
  for (const [name, path] of owners) {
    assert.match(page, new RegExp(`import \\{ ${name} \\} from "\\./${path}"`));
    assert.match(page, new RegExp(`<${name}\\b`));
  }
  assert.match(page, /import \{ useDocumentRenameWorkspace \} from "\.\.\/hooks\/use-document-rename-workspace"/);
  assert.match(page, /const model = useDocumentRenameWorkspace\(\)/);
  return [page, read("../hooks/use-document-rename-workspace.ts"),
    ...owners.map(([, path]) => read(`./${path}.tsx`))].join("\n");
}
