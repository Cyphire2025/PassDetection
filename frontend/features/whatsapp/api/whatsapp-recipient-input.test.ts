import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { whatsappApi } from "./whatsapp.api";
import { composerApi } from "../workspace/composer.api";
import { WhatsAppSendIntent } from "../utils/normal-send-intent";
const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { post } }));
beforeEach(() => useAuthStore.setState({ user: { id: "reviewed-owner", role: "agency_admin", agency_id: "agency-a" } as User, isAuthenticated: true }));

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
    await composerApi.send({ groupId: "broadcast-a", recipientIds: null, image: null,
      draft: { message_type: "reminder", message_content: "Please submit your passport details today.",
        audience: "not_submitted", audience_client_group_id: "client-group-a" } },
      new WhatsAppSendIntent("reviewed-reminder-request-1"));

    expect(post).toHaveBeenCalledWith(
      "/api/v1/whatsapp/groups/broadcast-a/send",
      {
        message_type: "reminder",
        message_content: "Please submit your passport details today.",
        recipient_ids: null,
        header_image_id: null,
        audience: "not_submitted",
        audience_client_group_id: "client-group-a",
      },
      { expectedOwnerUserId: "reviewed-owner", expectedAuthorityKey: '["reviewed-owner","agency_admin","agency-a"]', headers: { "Idempotency-Key": "reviewed-reminder-request-1" } },
    );
  });
});
