import { expect, it, vi } from "vitest";
const { get } = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { get } }));
import { uploadLinksApi } from "./upload-links.api";

it("keeps qualifier authorization in its header and forwards cancellation", async () => {
  const selection = { is_self: false, relation_code: "other", relation_label: "Cousin", status: "active" };
  get.mockResolvedValue({ data: selection });
  const controller = new AbortController();
  expect(await uploadLinksApi.getQualifierSelection("synthetic-trip", "synthetic-private-selection", controller.signal)).toBe(selection);
  expect(get).toHaveBeenCalledExactlyOnceWith("/api/v1/upload-links/token/synthetic-trip/qualifier-selection", {
    signal: controller.signal,
    headers: { "X-Upload-Session-ID": expect.any(String), "X-Qualifier-Selection-Token": "synthetic-private-selection" },
  });
});
