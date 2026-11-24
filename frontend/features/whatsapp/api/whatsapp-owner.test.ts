import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { WhatsAppSendIntent } from "../utils/normal-send-intent";
import { composerApi } from "../workspace/composer.api";

const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { post } }));
const owner = { id: "staff-a", role: "agency_admin", agency_id: "agency-a" } as User;
beforeEach(() => {
  post.mockReset().mockResolvedValue({ data: { queued: 1 } });
  useAuthStore.setState({ user: owner, isAuthenticated: true });
});

it("fails closed before creating a direct send intent without an initial actor", () => {
  useAuthStore.setState({ user: null, isAuthenticated: false });
  expect(() => new WhatsAppSendIntent("reviewed-synthetic-intent"))
    .toThrowError(expect.objectContaining({ code: "AUTH_REQUEST_OWNER_CHANGED" }));
  expect(post).not.toHaveBeenCalled();
});

it.each(["reminder", "passport_link"] as const)("does not dispatch an old %s after the account changes during reviewed-payload persistence", async (messageType) => {
  let release!: () => void;
  const intent = new WhatsAppSendIntent("reviewed-synthetic-intent", null, undefined,
    () => new Promise<void>((resolve) => { release = resolve; }));
  const operation = composerApi.send({ groupId: "group-a", recipientIds: ["recipient-a"], image: null,
    draft: { message_type: messageType, message_content: "Reviewed message" } }, intent);
  expect(release).toBeTypeOf("function");
  useAuthStore.setState({ user: { ...owner, id: "staff-b" } });
  release();
  await expect(operation).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  expect(post).not.toHaveBeenCalled();
});

it("does not dispatch the current composer after its image upload crosses accounts", async () => {
  let release!: (value: { data: { media_id: string } }) => void;
  post.mockImplementationOnce(() => new Promise((resolve) => { release = resolve; }));
  const operation = composerApi.send({ groupId: "group-a", recipientIds: ["recipient-a"],
    image: new File(["image"], "header.png", { type: "image/png" }),
    draft: { message_type: "welcome", message_content: "Reviewed message", header_image_id: null } },
    new WhatsAppSendIntent("reviewed-synthetic-upload"));
  useAuthStore.setState({ user: { ...owner, id: "staff-b" } });
  release({ data: { media_id: "old-owner-image" } });
  await expect(operation).rejects.toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
  expect(post).toHaveBeenCalledTimes(1);
});
