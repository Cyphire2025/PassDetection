import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

export function readOperationsApiSource() {
  const read = file => readFileSync(new URL(file, import.meta.url), "utf8");
  const facade = read("./operations.api.ts");
  const imports = new Map([...facade.matchAll(/import \{ (\w+) \} from "(\.\/operations-[\w-]+\.api)";/g)]
    .map(([, name, file]) => [name, file]));
  const methods = [...facade.matchAll(/^  (\w+): (\w+)\.\1,$/gm)];
  assert.equal(methods.length, 61);
  assert.equal(new Set(methods.map(([, name]) => name)).size, 61);
  const owners = new Map();
  for (const [, name, object] of methods) {
    const file = imports.get(object);
    assert.ok(file, `${name} has an imported domain owner`);
    if (!owners.has(file)) owners.set(file, read(`${file}.ts`));
    assert.ok(owners.get(file).includes(`export const ${object} = {`));
    assert.ok(owners.get(file).includes(`  ${name}: async (`));
  }
  const typeExports = [...facade.matchAll(/export type \{([^}]+)\} from "(\.\/operations-[\w-]+\.types)";/g)];
  let count = 0;
  for (const [, names, file] of typeExports) {
    const source = read(`${file}.ts`);
    owners.set(file, source);
    for (const name of names.split(",").map(name => name.trim()).filter(Boolean)) {
      assert.match(source, new RegExp(`export (?:interface|type) ${name}\\b`));
      count++;
    }
  }
  assert.equal(count, 64);
  assert.equal(owners.size, 14);
  return [facade, ...owners.values()].join("\n");
}
