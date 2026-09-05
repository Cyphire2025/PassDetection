import { readFileSync } from "node:fs";
import ts from "typescript";

const passportGroupDetailFiles = [
  "./passport-group-detail.tsx",
  "./use-passport-group-controller.tsx",
  "./passport-group-bindings.tsx",
  "./passport-group-model.tsx",
  "./passport-group-header-panel.tsx",
  "./passport-group-overview-panel.tsx",
  "./passport-group-import-panel.tsx",
  "./passport-group-selection-toolbar.tsx",
  "./passport-group-roster-panel.tsx",
  "./passport-group-dialogs.tsx",

  "./passport-document-cell.tsx",
  "./passport-document-import-dialog.tsx",
  "./passport-trip-details-dialog.tsx",
  "../utils/passport-document-import.ts",
  "../utils/passport-group-trip.ts",
];

export const passportGroupDetailSource = passportGroupDetailFiles
  .map((file) => readFileSync(new URL(file, import.meta.url), "utf8"))
  .join("\n");

export const passportGroupControllerSource = readFileSync(
  new URL("./use-passport-group-controller.tsx", import.meta.url), "utf8",
);

export const passportGroupCoordinatorSource = passportGroupDetailFiles.slice(0, 10)
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
