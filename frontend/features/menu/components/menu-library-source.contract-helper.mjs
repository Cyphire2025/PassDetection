import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

export function readMenuLibrarySource() {
  const read = file => readFileSync(new URL(file, import.meta.url), "utf8");
  const files = [
    "./menu-library.tsx", "../hooks/use-menu-library-controller.ts", "../types/menu-library.ts",
    "./menu-library-view.tsx", "./menu-category-rail.tsx", "./menu-category-workspace.tsx",
    "./menu-category-header.tsx", "./menu-dish-create-form.tsx", "./menu-library-dish-row.tsx",
  ];
  const sources = new Map(files.map(file => [file, read(file)]));
  const entry = sources.get("./menu-library.tsx");
  assert.match(entry, /import \{ useMenuLibraryController \} from "\.\.\/hooks\/use-menu-library-controller"/);
  assert.match(entry, /useMenuLibraryController\(categories\)/);
  assert.match(entry, /import \{ MenuLibraryView \} from "\.\/menu-library-view"/);
  assert.match(entry, /<MenuLibraryView model=\{model\}/);
  const wiring = [
    ["menu-library-view", "MenuCategoryRail", "menu-category-rail"],
    ["menu-library-view", "MenuCategoryWorkspace", "menu-category-workspace"],
    ["menu-category-workspace", "MenuCategoryHeader", "menu-category-header"],
    ["menu-category-workspace", "MenuDishCreateForm", "menu-dish-create-form"],
    ["menu-category-workspace", "MenuLibraryDishRow", "menu-library-dish-row"],
  ];
  for (const [owner, name, file] of wiring) {
    const source = sources.get(`./${owner}.tsx`);
    assert.ok(source.includes(`import { ${name} } from "./${file}"`));
    assert.match(source, new RegExp(`<${name}\\b`));
    assert.ok(sources.get(`./${file}.tsx`).includes(`export function ${name}(`));
  }
  for (const file of ["./menu-category-rail.tsx", "./menu-category-header.tsx"]) {
    assert.match(sources.get(file), /from "\.\.\/types\/menu-library"/);
  }
  assert.match(sources.get("../hooks/use-menu-library-controller.ts"), /from "\.\.\/types\/menu-library"/);
  return [...sources.values()].join("\n");
}
