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
const sidebarSource = readFileSync(
  new URL("../../../components/layout/sidebar.tsx", import.meta.url),
  "utf8",
);
const endpointsSource = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);

test("Menu is a first-class office sidebar destination", () => {
  assert.match(sidebarSource, /label: "Menu"/);
  assert.match(sidebarSource, /ROUTES\.dashboard\.menu/);
  assert.match(pageSource, /Dish Library/);
  assert.match(pageSource, /Meal Planner/);
});

test("planner exposes strict no-repeat generation and editable meals", () => {
  assert.match(plannerSource, /Generate Meal Plan/);
  assert.match(plannerSource, /No repeats/);
  assert.match(plannerSource, /usedDishIds/);
  assert.match(plannerSource, /onReplaceMeal/);
  assert.match(plannerSource, /Regenerate/);
});

test("menu UI uses the shared versioned API registry", () => {
  assert.match(endpointsSource, /workspace: "\/api\/v1\/menu"/);
  assert.match(endpointsSource, /generatePlan: "\/api\/v1\/menu\/plans\/generate"/);
  assert.match(endpointsSource, /planEntry:/);
});
