import { afterEach, beforeEach, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { saveBrandingImage } from "./branding-images.api";

vi.mock("@/lib/api/client", () => ({ default: { put: vi.fn(), delete: vi.fn() } }));
const actor = (id: string) => useAuthStore.setState({ user: { id, role: "agency_admin", agency_id: "agency" } as User });
beforeEach(() => { vi.resetAllMocks(); actor("initial-actor"); });
afterEach(() => useAuthStore.setState({ user: null }));

it("preserves the initiating account across a banner upload continuation", async () => {
  actor("replacement-actor");
  await expect(saveBrandingImage("group-banner", "group", "agency", new File(["synthetic"], "banner.jpg"), undefined, "initial-actor"))
    .rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  expect(apiClient.put).not.toHaveBeenCalled();
});

it.each(["upload", "remove"])("does not return a stale %s result to cache or UI callers", async (action) => {
  const respond = async () => { actor("replacement-actor"); return { data: { url: "/private-image", revision: 4 } }; };
  vi.mocked(apiClient.put).mockImplementation(respond);
  vi.mocked(apiClient.delete).mockImplementation(respond);
  await expect(saveBrandingImage("group-background", "group", "agency", action === "remove" ? null : new File(["synthetic"], "background.jpg")))
    .rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  const call = action === "remove" ? vi.mocked(apiClient.delete).mock.calls[0]?.[1] : vi.mocked(apiClient.put).mock.calls[0]?.[2];
  expect(call).toMatchObject({ expectedOwnerUserId: "initial-actor" });
});
