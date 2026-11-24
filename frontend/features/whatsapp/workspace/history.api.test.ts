import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { historyApi, type HistoryRecipient } from "./history.api";

afterEach(() => vi.restoreAllMocks());
const recipient: HistoryRecipient = {
  message_log_id: "original-log", recipient_id: "person", name: "Synthetic person",
  phone_number: "+919000000001", current_phone_number: "+919000000002", status: "failed",
  error_message: null, rendered_message: "Reviewed content", updated_at: "2026-01-01",
  removed: false, can_resend: true,
};
describe("current delivery history API", () => {
  it.each(["reminder", "passport_link", "welcome", "group_invite"])("retains original log and retry identity for %s", async (messageType) => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { batch_id: "accepted" } });
    const result = await historyApi.resend("broadcast", messageType, recipient, "stable-request");
    expect(post).toHaveBeenCalledWith(API_ENDPOINTS.whatsapp.resendRecipientMessage("broadcast", "person"), {
      message_type: messageType, source_message_log_id: "original-log", request_id: "stable-request",
    });
    expect(result).toEqual({ batch_id: "accepted" });
  });
  it("uses document-update retry without overriding its saved message type", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: {} });
    await historyApi.resend("broadcast", "document_update", { ...recipient, recipient_id: "person/one" }, "same-key");
    expect(post).toHaveBeenCalledWith(`${API_ENDPOINTS.whatsapp.group("broadcast")}/recipients/person%2Fone/resend-update`, {
      source_message_log_id: "original-log", request_id: "same-key",
    });
  });
  it("passes bounded recipient filters, abort signal and encoded message identity", async () => {
    const get = vi.spyOn(apiClient, "get").mockResolvedValue({ data: { items: [], total: 0 } });
    const params = { status_filter: "failed" as const, q: "Synthetic", offset: 50, limit: 50 };
    const signal = new AbortController().signal;
    await historyApi.recipients("broadcast", "batch/one", params, signal);
    expect(get).toHaveBeenCalledWith(`${API_ENDPOINTS.whatsapp.group("broadcast")}/messages/batch%2Fone/recipients`, { params, signal });
  });
});
