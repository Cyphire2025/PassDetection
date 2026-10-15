import { expect, it } from "vitest";
import { companyGroupHref, companyPersonHref, safeCompanyReturn } from "./company-navigation";

it("preserves the exact company or person view when a group is opened", () => {
  const person = companyPersonHref("company", "person", "tab=data&peopleSearch=Jane+Doe&peopleSort=name_desc&personTab=trips");
  expect(safeCompanyReturn(person)).toBe(person);
  expect(new URL(companyGroupHref("group", person), "https://local.test").searchParams.get("returnTo")).toBe(person);
});

it.each(["https://evil.test/companies/company", "//evil.test/companies/company", "javascript:alert(1)",
  "/companies/../settings", "/companies/company/../../settings", "/companies/company/settings", "/companies/company\\..\\settings", null])(
  "rejects a return destination outside the company directory: %s", (value) => expect(safeCompanyReturn(value)).toBeNull(),
);
