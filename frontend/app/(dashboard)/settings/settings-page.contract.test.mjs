import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
const policy = readFileSync(
  new URL("../../../features/settings/platform-settings-policy.ts", import.meta.url),
  "utf8",
);

test("settings remain unavailable until an authoritative load succeeds", () => {
  assert.match(page, /type SettingsLoadState = "loading" \| "ready" \| "error" \| "conflict"/);
  assert.match(page, /setLoadState\("ready"\)/);
  assert.match(page, /setLoadState\("error"\)/);
  assert.match(page, /disabled=\{loadState !== "ready"\}/);
  assert.match(page, /fieldset disabled=\{loadState !== "ready" \|\| isSaving\}/);
  assert.match(page, /destructive actions remain unavailable/);
});

test("writes carry a revision and preserve edits on an explicit conflict", () => {
  assert.match(policy, /expected_updated_at: expectedUpdatedAt/);
  assert.match(page, /PLATFORM_SETTINGS_REVISION_CONFLICT|isPlatformSettingsRevisionConflict/);
  assert.match(page, /setLoadState\("conflict"\)/);
  assert.match(page, /Your edits are preserved here/);
  assert.match(page, /Reload authoritative settings/);
  assert.doesNotMatch(page, /catch \(error\)[\s\S]{0,600}setSettings\(DEFAULT_PLATFORM_SETTINGS\)/);
});

test("the existing destructive approval flow accurately retains audit evidence", () => {
  assert.match(page, /DELETE_CONFIRMATION = "DELETE ALL DATA"/);
  assert.match(page, /setIsPurgeDialogOpen\(true\)/);
  assert.match(page, /Append-only audit evidence is retained/);
  assert.doesNotMatch(page, /notifications, audit entries, stored passport images/);
});
