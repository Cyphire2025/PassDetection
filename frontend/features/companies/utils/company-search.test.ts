import { expect, it } from "vitest";
import { companySearchHint } from "./company-search";

it("accepts normal partial names, full identifiers and normalized spaces", () => {
  for (const value of ["", "   ", "Ja Kum", " Jane   Kumar ", "44444444-4444-4444-8444-444444444444"]) {
    expect(companySearchHint(value)).toBeUndefined();
  }
});

it("guides short or oversized search parts before creating a request", () => {
  for (const value of ["J", "J Kumar"]) expect(companySearchHint(value)).toContain("at least 2");
  for (const value of ["a".repeat(33), "aa bb cc dd ee ff gg hh ii", "longname ".repeat(20)]) {
    expect(companySearchHint(value)).toContain("up to 8");
  }
});
