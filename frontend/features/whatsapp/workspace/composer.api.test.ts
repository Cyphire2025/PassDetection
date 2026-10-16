import { afterEach, describe, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { composerApi } from "./composer.api";
import type { WhatsAppSendIntent } from "../utils/normal-send-intent";

afterEach(() => vi.restoreAllMocks());

describe("shared broadcast dispatch contract", () => {
  it("removes preview sampling fields and binds the exact send body to its retained key", async () => {
    const post = vi
      .spyOn(apiClient, "post")
      .mockResolvedValue({ data: { batch_id: "batch", queued: 1 } });
    const bind = vi.fn().mockResolvedValue(undefined);
    const intent = {
      key: "retained-business-intent",
      bind,
    } as unknown as WhatsAppSendIntent;
    await composerApi.send(
      {
        groupId: "broadcast",
        image: null,
        recipientIds: ["selected-person"],
        draft: {
          message_type: "update",
          message_content: "A separate trip update",
          recipient_id: "preview-person",
          resend_recipient_id: null,
          recipient_ids: ["preview-person"],
          update_submission: "submitted",
          update_distribution: "pending",
          update_document_type: "visa",
        },
      },
      intent,
    );
    const payload = post.mock.calls[0][1];
    expect(payload).not.toHaveProperty("recipient_id");
    expect(payload).not.toHaveProperty("resend_recipient_id");
    expect(payload).toMatchObject({
      recipient_ids: ["selected-person"],
      update_submission: "submitted",
      update_distribution: "pending",
    });
    expect(bind).toHaveBeenCalledWith("broadcast", payload);
    expect(post.mock.calls[0][2]).toMatchObject({
      headers: { "Idempotency-Key": "retained-business-intent" },
    });
  });
});
