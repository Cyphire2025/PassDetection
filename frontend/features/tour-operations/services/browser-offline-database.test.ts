import { afterEach, describe, expect, it, vi } from "vitest";
import { openBrowserOfflineDatabase } from "./browser-offline-database";

describe("coordinator database connection ownership", () => {
  afterEach(() => vi.unstubAllGlobals());

  function opening() {
    const database = { close: vi.fn(), onversionchange: null as (() => void) | null };
    const request = { result: database, onsuccess: null as (() => void) | null, onblocked: null as (() => void) | null };
    vi.stubGlobal("indexedDB", { open: vi.fn(() => request) });
    return { database, request };
  }

  it("closes a late successful open after a blocked upgrade already rejected its caller", async () => {
    const { database, request } = opening();
    const result = openBrowserOfflineDatabase();
    const rejected = expect(result).rejects.toThrow("blocked by another tab");
    request.onblocked?.();
    await rejected;
    request.onsuccess?.();
    expect(database.close).toHaveBeenCalledExactlyOnceWith();
  });

  it("keeps a successful connection open until its version changes", async () => {
    const { database, request } = opening();
    const result = openBrowserOfflineDatabase();
    request.onsuccess?.();
    await expect(result).resolves.toBe(database);
    expect(database.close).not.toHaveBeenCalled();
    database.onversionchange?.();
    expect(database.close).toHaveBeenCalledExactlyOnceWith();
  });
});
