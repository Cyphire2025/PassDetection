import { beforeEach, expect, it, vi } from "vitest";
const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { post } }));
import { whatsappApi } from "./whatsapp.api";
beforeEach(() => { post.mockReset(); post.mockResolvedValue({ data: { queued: 1 } }); });
const link = "https://chat.whatsapp.com/Invite123?mode=ac_t";

it("sends a text-only invitation with the reviewed audience", async () => {
  await whatsappApi.sendGroupInvite({ groupId: "group", messageContent: "Join us.", groupInviteLink: link, recipientIds: ["A"] });
  expect(post).toHaveBeenCalledExactlyOnceWith("/api/v1/whatsapp/groups/group/send", { message_type: "group_invite", message_content: "Join us.", group_invite_link: link, recipient_ids: ["A"] });
});
it("retries one invite without uploading or passing unrelated image/passport fields", async () => {
  await whatsappApi.resendRecipientMessage({ groupId: "group", recipientId: "A", messageType: "group_invite", messageContent: "Join again.", groupInviteLink: link, passportIntro: "ignored", passportLink: "ignored", image: new File(["ignored"], "image.png"), headerImageId: "ignored", supportContactIds: ["ignored"] });
  expect(post).toHaveBeenCalledExactlyOnceWith("/api/v1/whatsapp/groups/group/recipients/A/resend", { message_type: "group_invite", message_content: "Join again.", group_invite_link: link });
});
it("uses the same two editable fields in bulk preview and idempotent resend", async () => {
  const selection = { groupId: "group", messageType: "group_invite" as const, recipientIds: ["A", "B"], overrides: { messageContent: "Edited invitation.", groupInviteLink: link } };
  await whatsappApi.previewRecipientsResend({ ...selection, previewRecipientId: "B" });
  await whatsappApi.resendRecipientsMessage({ ...selection, requestId: "request-1" });
  expect(post.mock.calls[0][1]).toEqual({ message_type: "group_invite", recipient_ids: ["A", "B"], preview_recipient_id: "B", message_content: "Edited invitation.", group_invite_link: link });
  expect(post.mock.calls[1][1]).toEqual({ message_type: "group_invite", recipient_ids: ["A", "B"], request_id: "request-1", message_content: "Edited invitation.", group_invite_link: link });
});
