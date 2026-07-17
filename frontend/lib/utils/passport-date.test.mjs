import assert from "node:assert/strict";
import test from "node:test";
import {
  formatPassportDateForUi,
  isPassportIsoDateWithinRange,
  isValidPassportIsoDate,
  maskPassportDateForUi,
  parsePassportDateFromUi,
  previousPassportIsoDate,
} from "./passport-date.ts";

test("round trips ISO storage and DD/MM/YYYY presentation", () => {
  assert.equal(formatPassportDateForUi("1972-08-30"), "30/08/1972");
  assert.equal(parsePassportDateFromUi("30/08/1972"), "1972-08-30");
});

test("validates real calendar dates and leap years", () => {
  assert.equal(parsePassportDateFromUi("29/02/2024"), "2024-02-29");
  assert.equal(parsePassportDateFromUi("29/02/2023"), null);
  assert.equal(parsePassportDateFromUi("31/04/2024"), null);
  assert.equal(parsePassportDateFromUi("00/08/1972"), null);
  assert.equal(isValidPassportIsoDate("2033-08-09"), true);
  assert.equal(isValidPassportIsoDate("2033-02-29"), false);
});

test("masks numeric typing into the required display format", () => {
  assert.equal(maskPassportDateForUi("3"), "3");
  assert.equal(maskPassportDateForUi("3008"), "30/08");
  assert.equal(maskPassportDateForUi("30-08-1972"), "30/08/1972");
  assert.equal(maskPassportDateForUi("30081972extra"), "30/08/1972");
});

test("enforces ISO date bounds without timezone conversion", () => {
  assert.equal(
    isPassportIsoDateWithinRange(
      "1972-08-30",
      "1900-01-01",
      "2026-07-17",
    ),
    true,
  );
  assert.equal(
    isPassportIsoDateWithinRange(
      "2026-07-18",
      "1900-01-01",
      "2026-07-17",
    ),
    false,
  );
});

test("computes the previous calendar date without a local timezone shift", () => {
  assert.equal(previousPassportIsoDate("2026-07-18"), "2026-07-17");
  assert.equal(previousPassportIsoDate("2024-03-01"), "2024-02-29");
  assert.equal(previousPassportIsoDate("2026-01-01"), "2025-12-31");
  assert.equal(previousPassportIsoDate("not-a-date"), null);
});
