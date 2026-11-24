import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

export function readOperationsHooksSource() {
  const read = name => readFileSync(new URL(`./${name}.ts`, import.meta.url), "utf8");
  const facade = read("use-operations");
  const bindings = [...facade.matchAll(/export \{ (\w+) \} from "\.\/(use-[\w-]+)";/g)];
  assert.equal(bindings.length, 34);
  assert.equal(new Set(bindings.map(([, name]) => name)).size, 34);
  const owners = new Map();
  for (const [, name, file] of bindings) {
    if (!owners.has(file)) owners.set(file, read(file));
    assert.ok(owners.get(file).includes(`export function ${name}(`));
  }
  for (const source of owners.values()) {
    if (/\busePrivateMutation\(/.test(source)) {
      assert.match(source, /import \{ usePrivateMutation \} from "@\/hooks\/use-private-mutation"/);
    }
    assert.doesNotMatch(source, /\buseMutation\(/);
    if (/useAuthenticatedQueryScope\(|roomingWorkspaceKey\(|MANAGED_ACCOUNTS_QUERY_KEY/.test(source)) {
      assert.match(source, /from "\.\/operations-query-scope"/);
    }
  }
  const combined = [facade, ...owners.values(), read("operations-query-scope")].join("\n");
  assert.equal((combined.match(/\busePrivateMutation\(/g) ?? []).length, 26);
  return combined;
}
