import { beforeEach, describe, expect, it, vi } from "vitest";

const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { post } }));
import { whatsappApi } from "./whatsapp.api";

describe("selected recipient resend API", () => {
  beforeEach(() => post.mockReset());

  it.each(["welcome", "passport_link"] as const)("sends only explicit %s selection and retains the request identity", async (messageType) => {
    const response = { selected: 2, queued: 2, batch_id: "batch-a", replayed: false };
    post.mockResolvedValue({data: response});
    const input = {
      groupId: "group-a", messageType, recipientIds: ["recipient-a", "recipient-c"],
      requestId: "bda4cb1b-56f7-43b4-9945-54ac6fed16c5",
    };
    expect(await whatsappApi.resendRecipientsMessage(input)).toEqual(response);
    expect(post).toHaveBeenCalledWith("/api/v1/whatsapp/groups/group-a/recipients/resend", {
      message_type: messageType, recipient_ids: ["recipient-a", "recipient-c"],
      request_id: input.requestId,
    });
    await whatsappApi.resendRecipientsMessage(input);
    expect(post.mock.calls[0]).toEqual(post.mock.calls[1]);
  });

  it.each([
    { recipientIds: [] }, { recipientIds: [""] }, { recipientIds: ["   "] },
    { recipientIds: ["recipient-a", "recipient-a"] },
  ])("never treats an invalid selection as the whole broadcast: $recipientIds", async ({ recipientIds }) => {
    await expect(whatsappApi.resendRecipientsMessage({
      groupId: "group-a", messageType: "welcome", recipientIds, requestId: "request-a",
    })).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });

  it("requires a retry identity before starting a delivery operation", async () => {
    await expect(whatsappApi.resendRecipientsMessage({
      groupId: "group-a", messageType: "passport_link", recipientIds: ["recipient-a"], requestId: "",
    })).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });
});
