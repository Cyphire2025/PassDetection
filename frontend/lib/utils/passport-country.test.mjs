import assert from "node:assert/strict";
import test from "node:test";
import {
  formatPassportCountry,
  formatPassportCountryField,
  formatPassportNationality,
  getPassportCountryOptions,
  getPassportNationalityOptions,
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

test("formats Indian nationality separately from the India issuing country", () => {
  for (const value of ["IN", "IND", "India", "indian"]) {
    assert.equal(formatPassportNationality(value), "Indian");
  }
  assert.equal(formatPassportNationality("USA"), "United States");
  assert.equal(formatPassportCountry("IND"), "India");
});

test("formats dashboard country fields without changing their raw values", () => {
  const submittedNationality = "IND";
  const submittedIssuingCountry = "IND";

  assert.equal(formatPassportCountryField("nationality", submittedNationality), "Indian");
  assert.equal(formatPassportCountryField("issuing_country", submittedIssuingCountry), "India");
  assert.equal(submittedNationality, "IND");
  assert.equal(submittedIssuingCountry, "IND");
});

test("builds options that retain raw API code shapes", () => {
  const alpha3India = getPassportCountryOptions(3).find((option) => option.value === "IND");
  const alpha2India = getPassportCountryOptions(2).find((option) => option.value === "IN");
  const nationalityIndia = getPassportNationalityOptions(3).find((option) => option.value === "IND");

  assert.deepEqual(alpha3India, { value: "IND", label: "India" });
  assert.deepEqual(alpha2India, { value: "IN", label: "India" });
  assert.deepEqual(nationalityIndia, { value: "IND", label: "Indian" });
  assert.equal(isRecognizedPassportCountryCode("IND"), true);
  assert.equal(isRecognizedPassportCountryCode("India"), false);
});
