import assert from "node:assert/strict";
import test from "node:test";
import { getPassportTextField } from "./passport-fields.ts";

test("reads only canonical place of issue without relabeling legacy country data", () => {
  assert.equal(
    getPassportTextField({ place_of_issue: "CHENNAI" }, "place_of_issue"),
    "CHENNAI",
  );
  assert.equal(
    getPassportTextField({ issuing_country: "India" }, "place_of_issue"),
    "",
  );
  assert.equal(
    getPassportTextField(
      { place_of_issue: "", issuing_country: "India" },
      "place_of_issue",
    ),
    "",
  );
});
