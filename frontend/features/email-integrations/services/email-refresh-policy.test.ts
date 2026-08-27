import { describe, expect, it } from "vitest";
import {
  EMAIL_REPAIR_PAGE_BUDGET,
  emailRepairIntervalMs,
} from "./email-refresh-policy";

describe("email repair refresh policy", () => {
  it("does not poll a hidden document", () => {
    expect(emailRepairIntervalMs({ visible: false })).toBe(false);
  });

  it("fully jitters idle repair between thirty and sixty seconds", () => {
    expect(emailRepairIntervalMs({ visible: true, random: () => 0 })).toBe(30_000);
    expect(emailRepairIntervalMs({ visible: true, random: () => 0.5 })).toBe(45_000);
    expect(emailRepairIntervalMs({ visible: true, random: () => 1 })).toBe(60_000);
  });

  it("uses a bounded active-processing repair lane", () => {
    expect(emailRepairIntervalMs({ active: true, visible: true, random: () => 0 })).toBe(5_000);
    expect(emailRepairIntervalMs({ active: true, visible: true, random: () => 1 })).toBe(10_000);
  });

  it("bounds retained operational inbox pages", () => {
    expect(EMAIL_REPAIR_PAGE_BUDGET).toBe(5);
  });
});
