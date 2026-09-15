import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const storageKey = "gc-download-sequence:v1";

describe("spreadsheet download filenames", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 8, 15, 9, 30, 0, 123));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("increments across export types and reloads even within the same millisecond", async () => {
    const { uniqueSpreadsheetFilename } = await import("./download-filename");
    expect(uniqueSpreadsheetFilename("Selected groups.xlsx"))
      .toBe("Selected groups-2026-09-15_09-30-00-123-0001.xlsx");
    expect(uniqueSpreadsheetFilename("Rooming.xlsx"))
      .toBe("Rooming-2026-09-15_09-30-00-123-0002.xlsx");
    vi.resetModules();
    const reloaded = await import("./download-filename");
    expect(reloaded.uniqueSpreadsheetFilename("Meal plan.xlsx"))
      .toBe("Meal plan-2026-09-15_09-30-00-123-0003.xlsx");
    expect(window.localStorage.getItem(storageKey)).toBe("3");
  });

  it("observes a counter advanced by another tab and sanitizes Windows filenames", async () => {
    const { uniqueSpreadsheetFilename } = await import("./download-filename");
    uniqueSpreadsheetFilename("test.xlsx");
    window.localStorage.setItem(storageKey, "42");
    expect(uniqueSpreadsheetFilename('Trip / Singapore: "Final".XLSX'))
      .toBe("Trip _ Singapore_ _Final_-2026-09-15_09-30-00-123-0043.xlsx");
  });

  it("still generates increasing names when browser storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const { uniqueSpreadsheetFilename } = await import("./download-filename");
    expect(uniqueSpreadsheetFilename("Trip.xlsx")).toMatch(/-0001\.xlsx$/);
    expect(uniqueSpreadsheetFilename("Trip.xlsx")).toMatch(/-0002\.xlsx$/);
  });

  it.each(["NaN", "-2", "3.5", "9007199254740991"])("ignores invalid stored sequence %s", async (stored) => {
    window.localStorage.setItem(storageKey, stored);
    const { uniqueSpreadsheetFilename } = await import("./download-filename");
    expect(uniqueSpreadsheetFilename("Trip.csv")).toMatch(/-0001\.csv$/);
  });

  it("keeps non-spreadsheet download names unchanged", async () => {
    const { uniqueSpreadsheetFilename } = await import("./download-filename");
    expect(uniqueSpreadsheetFilename("passport-images.zip")).toBe("passport-images.zip");
    expect(window.localStorage.getItem(storageKey)).toBeNull();
  });
});
