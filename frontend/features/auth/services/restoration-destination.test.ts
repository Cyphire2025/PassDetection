import { describe, expect, it } from "vitest";
import { safeRestorationDestination } from "./restoration-destination";

describe("safe restoration destination", () => {
  it("retains a protected page and search parameters", () => {
    expect(safeRestorationDestination("/passports/group-1?q=Anna")).toBe("/passports/group-1?q=Anna");
  });
  it.each([undefined, "https://outside.test", "//outside.test", "/\\outside.test", "/login?from=/login", "/session-restore", "/\n/outside.test"])("rejects external or looping destinations: %s", (input) => {
    expect(safeRestorationDestination(input)).toBe("/dashboard");
  });
});
