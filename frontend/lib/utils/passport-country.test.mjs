import assert from "node:assert/strict";
import test from "node:test";
import {
  formatPassportCountry,
  getPassportCountryOptions,
  isRecognizedPassportCountryCode,
} from "./passport-country.ts";

test("formats common two- and three-letter passport country codes", () => {
  assert.equal(formatPassportCountry("IND"), "India");
  assert.equal(formatPassportCountry("in"), "India");
  assert.equal(formatPassportCountry("USA"), "United States");
  assert.equal(formatPassportCountry("GBR"), "United Kingdom");
});

test("preserves country names and unknown values", () => {
  assert.equal(formatPassportCountry("India"), "India");
  assert.equal(formatPassportCountry("ZZZ"), "ZZZ");
  assert.equal(formatPassportCountry(""), "");
});

test("builds options that retain raw API code shapes", () => {
  const alpha3India = getPassportCountryOptions(3).find((option) => option.value === "IND");
  const alpha2India = getPassportCountryOptions(2).find((option) => option.value === "IN");

  assert.deepEqual(alpha3India, { value: "IND", label: "India" });
  assert.deepEqual(alpha2India, { value: "IN", label: "India" });
  assert.equal(isRecognizedPassportCountryCode("IND"), true);
  assert.equal(isRecognizedPassportCountryCode("India"), false);
});
