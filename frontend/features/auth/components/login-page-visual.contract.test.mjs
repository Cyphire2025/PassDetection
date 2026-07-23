import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const authLayout = readFileSync(
  new URL("../../../app/(auth)/layout.tsx", import.meta.url),
  "utf8",
);
const loginForm = readFileSync(new URL("./login-form.tsx", import.meta.url), "utf8");

test("login uses the team photo as a full-screen background with the form lowered", () => {
  assert.match(authLayout, /import Image from "next\/image"/);
  assert.match(authLayout, /import loginBackground from "\.\.\/\.\.\/public\/globalconnectteam\.png"/);
  assert.match(authLayout, /<Image[\s\S]*?src=\{loginBackground\}[\s\S]*?fill[\s\S]*?sizes="100vw"[\s\S]*?preload/);
  assert.match(authLayout, /object-cover object-center/);
  assert.match(authLayout, /items-end[\s\S]*?pt-\[clamp\(8rem,40dvh,28rem\)\]/);
});

test("login hides the standalone logo and keeps the form panel transparent", () => {
  assert.doesNotMatch(authLayout, /BrandLogo/);
  assert.match(loginForm, /className="bg-transparent p-3/);
  assert.doesNotMatch(loginForm, /rounded-xl border border-slate-200 bg-white p-8 shadow-sm/);
});
