import { beforeEach, expect, it, vi } from "vitest";
const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { post } }));
import { whatsappApi } from "./whatsapp.api";
beforeEach(() => { post.mockReset(); post.mockResolvedValue({ data: { queued: 1 } }); });
const link = "https://chat.whatsapp.com/Invite123?mode=ac_t";

it("sends the reviewed invitation image and audience", async () => {
  await whatsappApi.sendGroupInvite({ groupId: "group", messageContent: "Join us.", groupInviteLink: link, recipientIds: ["A"], image: null, headerImageId: "invite-image" });
  expect(post).toHaveBeenCalledExactlyOnceWith("/api/v1/whatsapp/groups/group/send", { message_type: "group_invite", message_content: "Join us.", group_invite_link: link, recipient_ids: ["A"], header_image_id: "invite-image" });
});
it("uploads a new invitation image before sending", async () => {
  post.mockResolvedValueOnce({ data: { media_id: "uploaded-image" } });
  const image = new File(["image bytes"], "invite.png", { type: "image/png" });
  await whatsappApi.sendGroupInvite({ groupId: "group", messageContent: "Join us.", groupInviteLink: link, recipientIds: ["A"], image, headerImageId: "old-image" });
  expect(post.mock.calls[0][0]).toBe("/api/v1/whatsapp/groups/group/welcome-media");
  expect((post.mock.calls[0][1] as FormData).get("image")).toBe(image);
  expect(post.mock.calls[1][1]).toMatchObject({ header_image_id: "uploaded-image", recipient_ids: ["A"] });
});
it("does not queue an invite when image upload fails", async () => {
  post.mockRejectedValueOnce(new Error("Upload failed"));
  await expect(whatsappApi.sendGroupInvite({ groupId: "group", messageContent: "Join us.", groupInviteLink: link, recipientIds: ["A"], image: new File(["image"], "invite.png"), headerImageId: null })).rejects.toThrow("Upload failed");
  expect(post).toHaveBeenCalledTimes(1);
});
it("retries one invite with a replacement image and no unrelated passport fields", async () => {
  post.mockResolvedValueOnce({ data: { media_id: "replacement-image" } });
  await whatsappApi.resendRecipientMessage({ groupId: "group", recipientId: "A", messageType: "group_invite", messageContent: "Join again.", groupInviteLink: link, passportIntro: "ignored", passportLink: "ignored", image: new File(["photo"], "image.png"), headerImageId: "old-image", supportContactIds: ["ignored"] });
  expect(post).toHaveBeenLastCalledWith("/api/v1/whatsapp/groups/group/recipients/A/resend", { message_type: "group_invite", message_content: "Join again.", group_invite_link: link, header_image_id: "replacement-image" });
});
it("reuses a saved image when retrying one invite", async () => {
  await whatsappApi.resendRecipientMessage({ groupId: "group", recipientId: "A", messageType: "group_invite", messageContent: "Join again.", groupInviteLink: link, passportIntro: "", passportLink: "", image: null, headerImageId: "saved-image" });
  expect(post).toHaveBeenCalledExactlyOnceWith("/api/v1/whatsapp/groups/group/recipients/A/resend", { message_type: "group_invite", message_content: "Join again.", group_invite_link: link, header_image_id: "saved-image" });
});
it("uses the same edited message, link and photo in bulk preview and idempotent resend", async () => {
  const selection = { groupId: "group", messageType: "group_invite" as const, recipientIds: ["A", "B"], overrides: { messageContent: "Edited invitation.", groupInviteLink: link, headerImageId: "bulk-image" } };
  await whatsappApi.previewRecipientsResend({ ...selection, previewRecipientId: "B" });
  await whatsappApi.resendRecipientsMessage({ ...selection, requestId: "request-1" });
  expect(post.mock.calls[0][1]).toEqual({ message_type: "group_invite", recipient_ids: ["A", "B"], preview_recipient_id: "B", message_content: "Edited invitation.", group_invite_link: link, header_image_id: "bulk-image" });
  expect(post.mock.calls[1][1]).toEqual({ message_type: "group_invite", recipient_ids: ["A", "B"], request_id: "request-1", message_content: "Edited invitation.", group_invite_link: link, header_image_id: "bulk-image" });
});
