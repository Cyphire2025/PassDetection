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

  it("previews and resends the same edits without forwarding a shared passport link", async () => {
    post.mockResolvedValue({ data: {} });
    const overrides = {
      messageContent: "Please complete your details by Friday.",
      passportIntro: "Here is your secure upload link.",
      headerImageId: "uploaded-image-a",
      supportContactIds: ["support-a"],
      passportLink: "https://example.test/private-link-for-one-person",
    };
    const selection = {
      groupId: "group-a", messageType: "passport_link" as const,
      recipientIds: ["recipient-a", "recipient-b"], overrides,
    };
    const controller = new AbortController();
    await whatsappApi.previewRecipientsResend({ ...selection, previewRecipientId: "recipient-b", signal: controller.signal });
    await whatsappApi.resendRecipientsMessage({ ...selection, requestId: "same-reviewed-operation" });
    expect(post.mock.calls[0][0]).toBe("/api/v1/whatsapp/groups/group-a/recipients/resend/preview");
    expect(post.mock.calls[0][2]).toEqual({ signal: controller.signal });
    const { preview_recipient_id, ...previewBody } = post.mock.calls[0][1];
    const { request_id, ...sendBody } = post.mock.calls[1][1];
    expect(preview_recipient_id).toBe("recipient-b");
    expect(request_id).toBe("same-reviewed-operation");
    expect(sendBody).toEqual(previewBody);
    expect(sendBody).toEqual({
      message_type: "passport_link", recipient_ids: ["recipient-a", "recipient-b"],
      message_content: overrides.messageContent, passport_intro: overrides.passportIntro,
      header_image_id: "uploaded-image-a", support_contact_ids: ["support-a"],
    });
  });

  it("keeps untouched fields null when switching the sampled recipient", async () => {
    post.mockResolvedValue({ data: {} });
    const selection = {
      groupId: "group-a", messageType: "passport_link" as const,
      recipientIds: ["recipient-a", "recipient-b"],
      overrides: { messageContent: null, passportIntro: null, headerImageId: null, supportContactIds: null },
    };
    for (const previewRecipientId of selection.recipientIds) {
      await whatsappApi.previewRecipientsResend({ ...selection, previewRecipientId });
    }
    const { preview_recipient_id: firstRecipient, ...firstDraft } = post.mock.calls[0][1];
    const { preview_recipient_id: secondRecipient, ...secondDraft } = post.mock.calls[1][1];
    expect(firstRecipient).not.toEqual(secondRecipient);
    expect(firstDraft).toEqual(secondDraft);
    expect(firstDraft.message_content).toBeNull();
    expect(firstDraft.passport_intro).toBeNull();
    expect(firstDraft.header_image_id).toBeNull();
    expect(firstDraft.support_contact_ids).toBeNull();
  });

  it("lets the server choose an eligible saved message for the initial preview", async () => {
    post.mockResolvedValue({ data: {} });
    await whatsappApi.previewRecipientsResend({
      groupId: "group-a", messageType: "welcome", recipientIds: ["recipient-a", "recipient-b"],
    });
    expect(post.mock.calls[0][1]).toEqual({
      message_type: "welcome", recipient_ids: ["recipient-a", "recipient-b"], preview_recipient_id: null,
    });
  });

  it("rejects a preview person outside the selected audience before requesting a private link", async () => {
    await expect(whatsappApi.previewRecipientsResend({
      groupId: "group-a", messageType: "passport_link", recipientIds: ["recipient-a"], previewRecipientId: "recipient-b",
    })).rejects.toThrow("Choose a preview recipient from the selected people.");
    expect(post).not.toHaveBeenCalled();
  });

  it("never previews the whole broadcast when the selection is empty", async () => {
    await expect(whatsappApi.previewRecipientsResend({
      groupId: "group-a", messageType: "welcome", recipientIds: [],
    })).rejects.toThrow();
    expect(post).not.toHaveBeenCalled();
  });
});

describe("recipient import and reminder audience API contracts", () => {
  beforeEach(() => post.mockReset());

  it("preserves previewed spreadsheet headings when creating and extending a broadcast", async () => {
    post.mockResolvedValue({ data: {} });
    const importedFieldKeys = [
      "name",
      "mobile_number",
      "producer_code",
      "empty_location_column",
    ];

    await whatsappApi.createGroup({
      name: "September Tour",
      contacts: [{ name: "Aarav", phone_number: "+919818752221" }],
      rejectedContacts: [],
      supportContacts: [],
      recipientOptInConfirmed: true,
      importedFieldKeys,
    });
    await whatsappApi.addRecipients({
      groupId: "broadcast-a",
      contacts: [{ name: "Meera", phone_number: "+919999911111" }],
      rejectedContacts: [],
      recipientOptInConfirmed: true,
      importedFieldKeys,
    });

    const createBody = post.mock.calls[0]?.[1] as FormData;
    const addBody = post.mock.calls[1]?.[1] as FormData;
    expect(createBody.get("imported_field_keys_json")).toBe(JSON.stringify(importedFieldKeys));
    expect(addBody.get("imported_field_keys_json")).toBe(JSON.stringify(importedFieldKeys));
    expect(post.mock.calls[0]?.[0]).toBe("/api/v1/whatsapp/groups");
    expect(post.mock.calls[1]?.[0]).toBe("/api/v1/whatsapp/groups/broadcast-a/recipients");
  });

  it("sends the reviewed not-submitted audience against one explicit linked group", async () => {
    post.mockResolvedValue({ data: { queued: 2 } });
    await whatsappApi.sendReminder(
      "broadcast-a",
      "Please submit your passport details today.",
      null,
      "not_submitted",
      "client-group-a",
    );

    expect(post).toHaveBeenCalledWith(
      "/api/v1/whatsapp/groups/broadcast-a/send",
      {
        message_type: "reminder",
        message_content: "Please submit your passport details today.",
        recipient_ids: null,
        audience: "not_submitted",
        audience_client_group_id: "client-group-a",
      },
    );
  });
});
