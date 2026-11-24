import { readFileSync } from "node:fs";
import ts from "typescript";

const passportGroupDetailFiles = [
  "./passport-group-detail.tsx",
  "./use-passport-group-controller.tsx",
  "./use-passport-group-selection.ts",
  "./use-passport-group-view.ts",
  "./use-passport-group-metadata.ts",
  "./use-passport-group-menus.ts",
  "./use-passport-group-imports.ts",
  "./use-passport-group-dialog-state.ts",
  "./use-passport-selected-image-download.ts",
  "./passport-group-bindings.tsx",
  "./passport-group-model.tsx",
  "./passport-group-duplicates.tsx",
  "./passport-mobile-card.tsx",
  "./reextract-passport-control.tsx",
  "./passport-group-fields.tsx",
  "./passport-group-feedback.ts",
  "./passport-group-header-panel.tsx",
  "./passport-group-overview-panel.tsx",
  "./passport-group-import-panel.tsx",
  "./passport-group-selection-toolbar.tsx",
  "./passport-group-roster-panel.tsx",
  "./passport-group-roster-table.tsx",
  "./passport-group-dialogs.tsx",

  "./passport-document-matrix.tsx",
  "./passport-document-cell.tsx",
  "./passport-document-import-dialog.tsx",
  "./passport-trip-details-dialog.tsx",
  "./passport-group-readiness.tsx",
  "../utils/passport-document-import.ts",
  "../utils/passport-group-trip.ts",
  "../utils/passport-group-update.ts",
  "../utils/passport-request-id.ts",
  "./passport-group-filter-controls.tsx",
  "./passport-group-selected-actions.tsx",
  "./use-passport-bulk-menu-position.ts",
];

export const passportGroupDetailSource = passportGroupDetailFiles
  .map((file) => readFileSync(new URL(file, import.meta.url), "utf8"))
  .join("\n");

export const passportGroupControllerSource = [
  "./use-passport-group-controller.tsx", "./use-passport-group-selection.ts",
  "./use-passport-group-view.ts", "./use-passport-group-metadata.ts",
  "./use-passport-group-menus.ts", "./use-passport-group-imports.ts",
  "./use-passport-group-dialog-state.ts", "./use-passport-selected-image-download.ts",
].map((file) => readFileSync(new URL(file, import.meta.url), "utf8")).join("\n");

export const passportGroupCoordinatorSource = passportGroupDetailFiles.slice(0, 23)
  .map((file) => readFileSync(new URL(file, import.meta.url), "utf8"))
  .join("\n");

/** Inspect one handler body without accidentally matching an adjacent module. */
export function passportGroupHandlerBody(name) {
  const sourceFile = ts.createSourceFile(
    "use-passport-group-controller.tsx", passportGroupControllerSource,
    ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX,
  );
  let body;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === name
      && node.initializer && ts.isArrowFunction(node.initializer)) {
      body = node.initializer.body.getText(sourceFile);
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  if (!body) throw new Error(`Missing passport group handler: ${name}`);
  return body;
}
