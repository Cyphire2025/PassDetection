import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const DIALOG_MODULES = new Set([
  "document-workspace-dialogs.tsx",
  "abort-incomplete-upload-dialog.tsx",
  "remove-document-assignments-dialog.tsx",
  "document-delivery-preview-dialog.tsx",
  "document-delivery-preview-props.ts",
  "document-delivery-preview-summary.tsx",
  "document-delivery-message-fields.tsx",
  "document-delivery-recipient-table.tsx",
  "document-delivery-preview-footer.tsx",
]);

/** Follow the actual facade exports and focused owner imports used at runtime. */
export function readDocumentDialogsSource() {
  const visited = new Map();
  const visit = (url) => {
    const name = basename(fileURLToPath(url));
    if (visited.has(name)) return;
    const source = readFileSync(url, "utf8");
    visited.set(name, source);
    const tree = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true);
    for (const statement of tree.statements) {
      if (!ts.isImportDeclaration(statement) && !ts.isExportDeclaration(statement)) continue;
      if (!statement.moduleSpecifier || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
      const specifier = statement.moduleSpecifier.text;
      if (!specifier.startsWith("./")) continue;
      for (const extension of [".tsx", ".ts"]) {
        const dependency = new URL(`${specifier}${extension}`, url);
        if (DIALOG_MODULES.has(basename(fileURLToPath(dependency)))) visit(dependency);
      }
    }
  };
  visit(new URL("./document-workspace-dialogs.tsx", import.meta.url));
  assert.deepEqual(new Set(visited.keys()), DIALOG_MODULES, "Every dialog owner must remain connected to the facade");
  return [...visited.values()].join("\n");
}
