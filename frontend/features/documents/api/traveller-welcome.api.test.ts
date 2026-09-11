import { beforeEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { travellerWelcomeApi } from "./traveller-welcome.api";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), post: vi.fn() } }));

describe("traveller welcome API", () => {
  beforeEach(() => vi.clearAllMocks());
  it("binds preview to group, source, replacement image and cancellation signal", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ data: { preview_token: "token" } });
    const signal = new AbortController().signal;
    await travellerWelcomeApi.preview("trip", "original-broadcast", "replacement-image", signal);
    expect(apiClient.get).toHaveBeenCalledExactlyOnceWith("/api/v1/document-distribution/groups/trip/whatsapp-welcome-preview", { params: { source_broadcast_id: "original-broadcast", header_image_id: "replacement-image" }, signal });
  });
  it("sends only reviewed numbers with their exact preview token and source", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ data: { queued_count: 1 } });
    const request = { phone_numbers: ["+919900000001"], preview_token: "token", source_broadcast_id: "original-broadcast", header_image_id: "replacement-image" };
    await travellerWelcomeApi.send("trip", request);
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/api/v1/document-distribution/groups/trip/whatsapp-welcome-send", request);
  });
});
