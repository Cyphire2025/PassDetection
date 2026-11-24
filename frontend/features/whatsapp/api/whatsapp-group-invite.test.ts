import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { composerApi } from "../workspace/composer.api";
import { WhatsAppSendIntent } from "../utils/normal-send-intent";
const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { post } }));
beforeEach(() => {
  post.mockReset().mockResolvedValue({ data: { queued: 1 } });
  useAuthStore.setState({ user: { id: "invite-owner", role: "agency_admin", agency_id: "agency-a" } as User, isAuthenticated: true });
});
const link = "https://chat.whatsapp.com/Invite123?mode=ac_t";
const requestKey = "reviewed-invitation-request-1";
const input = (image: File | null, headerImageId: string | null) => ({
  groupId: "group", recipientIds: ["A"], image,
  draft: { message_type: "group_invite" as const, message_content: "Join us.", group_invite_link: link, header_image_id: headerImageId },
});

it("sends the reviewed invitation image and audience through the current composer", async () => {
  await composerApi.send(input(null, "invite-image"), new WhatsAppSendIntent(requestKey));
  expect(post).toHaveBeenCalledExactlyOnceWith("/api/v1/whatsapp/groups/group/send", {
    message_type: "group_invite", message_content: "Join us.", group_invite_link: link,
    recipient_ids: ["A"], header_image_id: "invite-image",
  }, { expectedOwnerUserId: "invite-owner", expectedAuthorityKey: '["invite-owner","agency_admin","agency-a"]', headers: { "Idempotency-Key": requestKey } });
});
it("uploads a new invitation image before sending", async () => {
  post.mockResolvedValueOnce({ data: { media_id: "uploaded-image" } });
  const image = new File(["image bytes"], "invite.png", { type: "image/png" });
  await composerApi.send(input(image, "old-image"), new WhatsAppSendIntent(requestKey));
  expect(post.mock.calls[0][0]).toBe("/api/v1/whatsapp/groups/group/welcome-media");
  expect((post.mock.calls[0][1] as FormData).get("image")).toBe(image);
  expect(post.mock.calls[1][1]).toMatchObject({ header_image_id: "uploaded-image", recipient_ids: ["A"] });
});
it("does not queue an invite when image upload fails", async () => {
  post.mockRejectedValueOnce(new Error("Upload failed"));
  await expect(composerApi.send(input(new File(["image"], "invite.png"), null), new WhatsAppSendIntent(requestKey))).rejects.toThrow("Upload failed");
  expect(post).toHaveBeenCalledTimes(1);
});
