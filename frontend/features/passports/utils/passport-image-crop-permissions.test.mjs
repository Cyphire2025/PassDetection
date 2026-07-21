import assert from "node:assert/strict";
import test from "node:test";

import { canEditPassportImages } from "./passport-image-crop-permissions.ts";

test("office editor roles can crop passport images", () => {
  for (const role of ["super_admin", "agency_admin", "agency_manager", "agency_staff"]) {
    assert.equal(canEditPassportImages(role), true, role);
  }
});

test("coordinators and unauthenticated viewers cannot crop passport images", () => {
  assert.equal(canEditPassportImages("agency_coordinator"), false);
  assert.equal(canEditPassportImages(null), false);
  assert.equal(canEditPassportImages(undefined), false);
});
