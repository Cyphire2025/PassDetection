import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const authLayout = readFileSync(
  new URL("../../../app/(auth)/layout.tsx", import.meta.url),
  "utf8",
);
const loginForm = readFileSync(new URL("./login-form.tsx", import.meta.url), "utf8");

test("login uses the team photo as a full-screen background with the form lowered", () => {
  assert.match(authLayout, /backgroundImage: "url\('\/globalconnectteam\.png'\)"/);
  assert.match(authLayout, /min-h-dvh[\s\S]*?bg-cover[\s\S]*?bg-center/);
  assert.match(authLayout, /items-end[\s\S]*?pt-\[44vh\]/);
  assert.match(authLayout, /translate-y-\[3vh\]/);
});

test("login hides the standalone logo and keeps the form panel transparent", () => {
  assert.doesNotMatch(authLayout, /BrandLogo/);
  assert.match(loginForm, /className="bg-transparent p-3/);
  assert.doesNotMatch(loginForm, /rounded-xl border border-slate-200 bg-white p-8 shadow-sm/);
});
