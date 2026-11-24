import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

// Present the actual, connected owners in the original contract's logical order.
// Assertions remain against current implementation, never archived source text.
export function readAttendanceQueueSource() {
  const owners = ["contracts", "commands", "replay", "outcomes", "delivery-state",
    "closeout", "storage", "discards", "migration", "codec", "runtime", "idb", "errors"];
  const read = (file) => readFileSync(new URL(file, import.meta.url), "utf8");
  const modules = new Map(owners.map((name) => [`./attendance-queue-${name}`, read(`./attendance-queue-${name}.ts`)]));
  modules.set("./attendance-scan-queue", read("./attendance-scan-queue.ts"));
  modules.set("./attendance-batch-selection", read("./attendance-batch-selection.ts"));
  const visited = new Set();
  const walk = (name) => {
    if (visited.has(name)) return;
    visited.add(name);
    const source = modules.get(name);
    const tree = ts.createSourceFile(`${name}.ts`, source, ts.ScriptTarget.Latest, true);
    for (const node of tree.statements) {
      if ((!ts.isImportDeclaration(node) && !ts.isExportDeclaration(node)) || !node.moduleSpecifier) continue;
      const target = node.moduleSpecifier.text;
      if (!modules.has(target)) continue;
      const targetTree = ts.createSourceFile(`${target}.ts`, modules.get(target), ts.ScriptTarget.Latest, true);
      const exports = new Set(targetTree.statements.filter((item) => item.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)).flatMap((item) => (
        ts.isVariableStatement(item) ? item.declarationList.declarations.map((value) => value.name.getText(targetTree)) : [item.name?.getText(targetTree)]
      )));
      const bindings = ts.isImportDeclaration(node) ? node.importClause?.namedBindings : node.exportClause;
      for (const binding of bindings?.elements ?? []) {
        assert.ok(exports.has(binding.propertyName?.text ?? binding.name.text), `Missing actual export in ${target}`);
      }
      walk(target);
    }
  };
  walk("./attendance-scan-queue");
  assert.equal(visited.size, modules.size, "Every aggregated owner must be connected to the actual public queue");
  return [modules.get("./attendance-scan-queue"), ...owners.map((name) => modules.get(`./attendance-queue-${name}`)), modules.get("./attendance-batch-selection")].join("\n");
}
