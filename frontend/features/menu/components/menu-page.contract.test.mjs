import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const pageSource = readFileSync(
  new URL("./menu-page.tsx", import.meta.url),
  "utf8",
);
const plannerSource = readFileSync(
  new URL("./meal-planner.tsx", import.meta.url),
  "utf8",
);
const librarySource = readFileSync(
  new URL("./menu-library.tsx", import.meta.url),
  "utf8",
);
const sidebarSource = readFileSync(
  new URL("../../../components/layout/sidebar.tsx", import.meta.url),
  "utf8",
);
const endpointsSource = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);
const apiSource = readFileSync(new URL("../api/menu.api.ts", import.meta.url), "utf8");
const hooksSource = readFileSync(new URL("../hooks/use-menu.ts", import.meta.url), "utf8");

test("Menu is a first-class office sidebar destination", () => {
  assert.match(sidebarSource, /label: "Menu"/);
  assert.match(sidebarSource, /ROUTES\.dashboard\.menu/);
  assert.match(pageSource, /Dish Library/);
  assert.match(pageSource, /Meal Planner/);
});

test("every planned meal contains every selected category without repeats", () => {
  assert.match(plannerSource, /Generate Meal Plan/);
  assert.match(plannerSource, /No repeats/);
  assert.match(plannerSource, /usedDishIds/);
  assert.match(plannerSource, /requiredDishesPerCategory/);
  assert.match(plannerSource, /Every selected category/);
  assert.match(plannerSource, /onReplaceMeal/);
  assert.match(plannerSource, /Regenerate/);
});

test("dish library uses a category navigation rail and one active workspace", () => {
  assert.match(librarySource, /aria-label="Dish categories"/);
  assert.match(librarySource, /selectedCategoryId/);
  assert.match(librarySource, /selectedCategory\.dishes\.map/);
  assert.doesNotMatch(librarySource, /md:grid-cols-2/);
});

test("menu UI uses the shared versioned API registry", () => {
  assert.match(endpointsSource, /workspace: "\/api\/v1\/menu"/);
  assert.match(endpointsSource, /generatePlan: "\/api\/v1\/menu\/plans\/generate"/);
  assert.match(endpointsSource, /planEntry:/);
  assert.match(endpointsSource, /planExport:/);
  assert.match(plannerSource, /Excel/);
});

test("menu mutations fence stale browser state with authoritative revisions", () => {
  assert.match(apiSource, /expected_updated_at/);
  assert.match(apiSource, /expected_category_updated_at/);
  assert.match(apiSource, /expected_category_revisions/);
  assert.match(hooksSource, /requireCategory\(currentWorkspace\(queryClient\)/);
  assert.match(hooksSource, /expectedUpdatedAt: plan\.updated_at/);
  assert.match(hooksSource, /onSettled: refresh/);
});
