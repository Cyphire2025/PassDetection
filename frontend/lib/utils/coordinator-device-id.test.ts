import { afterEach, expect, it, vi } from "vitest";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});

it("reuses the stored browser device identity", async () => {
  localStorage.setItem("passdetection-coordinator-device-id", "existing-device");
  const { getCoordinatorDeviceId } = await import("./coordinator-device-id");
  expect(getCoordinatorDeviceId()).toBe("existing-device");
});

it.each(["getItem", "setItem"] as const)("keeps a stable ID when storage %s throws", async (method) => {
  vi.resetModules();
  vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new DOMException("Denied"); });
  const { getCoordinatorDeviceId } = await import("./coordinator-device-id");
  const first = getCoordinatorDeviceId();
  expect(first).toBeTruthy();
  expect(getCoordinatorDeviceId()).toBe(first);
});

it("supports browsers without randomUUID and persists the same ID on recovery", async () => {
  vi.resetModules();
  vi.stubGlobal("crypto", {});
  const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => {
    throw new DOMException("Quota exceeded");
  });
  const { getCoordinatorDeviceId } = await import("./coordinator-device-id");
  const first = getCoordinatorDeviceId();
  expect(getCoordinatorDeviceId()).toBe(first);
  expect(storage).toHaveBeenLastCalledWith("passdetection-coordinator-device-id", first);
});
