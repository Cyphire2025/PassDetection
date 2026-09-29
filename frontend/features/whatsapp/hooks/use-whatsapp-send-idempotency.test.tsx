import { webcrypto } from "node:crypto";
import { type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WhatsAppReminderAudience } from "../api/whatsapp.api";
import { NORMAL_SEND_STORAGE_PREFIX, UncertainWhatsAppSendError } from "../utils/normal-send-storage";
import { WhatsAppSendIntent } from "../utils/normal-send-intent";
import {
  useSendWhatsAppGroupInvite, useSendWhatsAppPassportLink,
  useSendWhatsAppReminder, useSendWhatsAppWelcome,
} from "./use-whatsapp";

const mocks = vi.hoisted(() => ({ post: vi.fn(), actor: { id: "user-a", agency_id: "agency-a" } }));
vi.mock("@/lib/api/client", () => ({ default: { post: mocks.post } }));
vi.mock("@/stores/auth.store", () => ({ useAuthStore: { getState: () => ({ user: mocks.actor }) } }));
const modes = ["welcome", "reminder", "passport", "invite"] as const;
const receipt = { batch_id: "retained-batch", queued: 2, sent: 0, failed: 0, message: "Queued" };
const networkError = new Error("Response lost after queueing");

function variables() {
  return {
    groupId: "group-a", messageContent: "Reviewed message", recipientIds: ["person-b", "person-a"],
    image: null as File | null, headerImageId: "saved-image", passportIntro: "Upload your passport",
    passportLink: "https://example.test/upload/reviewed", supportContactIds: ["support-a"],
    groupInviteLink: "https://chat.whatsapp.com/ReviewedInvite", audience: "all" as WhatsAppReminderAudience,
    audienceClientGroupId: "client-group-a",
  };
}

function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: 2 } } });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const rendered = renderHook(() => ({
    welcome: useSendWhatsAppWelcome(), reminder: useSendWhatsAppReminder(),
    passport: useSendWhatsAppPassportLink(), invite: useSendWhatsAppGroupInvite(),
  }), { wrapper });
  return { ...rendered, client };
}

function sendCalls() { return mocks.post.mock.calls.filter(([url]) => String(url).endsWith("/send")); }
function key(index: number) { return sendCalls()[index][2].headers["Idempotency-Key"] as string; }

async function approveChangedIntent(send: () => Promise<unknown>) {
  await act(async () => {
    let error: unknown;
    try { await send(); } catch (cause) { error = cause; }
    if (error instanceof UncertainWhatsAppSendError) {
      const before = sendCalls().length;
      error.startNew();
      expect(sendCalls()).toHaveLength(before);
      await expect(send()).rejects.toBe(networkError);
    } else {
      expect(error).toBe(networkError);
    }
  });
}

beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  window.sessionStorage.clear();
  mocks.post.mockReset();
  mocks.actor = { id: "user-a", agency_id: "agency-a" };
});

afterEach(() => vi.unstubAllGlobals());

describe("normal WhatsApp reviewed-send identity", () => {
  it.each(modes)("retains the exact %s request and key after an unknown response and rerender", async (mode) => {
    mocks.post.mockRejectedValueOnce(networkError).mockResolvedValue({ data: receipt });
    const { result, rerender } = setup();
    const input = variables();
    await act(async () => { await expect(result.current[mode].mutateAsync(input)).rejects.toBe(networkError); });
    // A configured query-client retry does not silently submit another send.
    expect(sendCalls()).toHaveLength(1);
    rerender();
    await act(async () => { expect(await result.current[mode].mutateAsync({ ...input })).toEqual(receipt); });
    expect(sendCalls()[1]).toEqual(sendCalls()[0]);
    expect(key(0)).toMatch(/^[0-9a-f-]{36}$/);
    expect(sendCalls()[0][1].recipient_ids).toEqual(["person-a", "person-b"]);
  });

  it.each(["welcome", "passport", "invite"] as const)("uploads %s media once across uncertain send retries", async (mode) => {
    let sends = 0;
    mocks.post.mockImplementation(async (url: string) => {
      if (url.endsWith("/welcome-media")) return { data: { media_id: "resolved-image" } };
      if (++sends === 1) throw networkError;
      return { data: receipt };
    });
    const { result } = setup();
    const input = { ...variables(), image: new File(["image bytes"], "reviewed.png", { type: "image/png" }) };
    await act(async () => { await expect(result.current[mode].mutateAsync(input)).rejects.toBe(networkError); });
    await act(() => result.current[mode].mutateAsync(input));
    expect(mocks.post.mock.calls.filter(([url]) => String(url).endsWith("/welcome-media"))).toHaveLength(1);
    expect(sendCalls()[0][1].header_image_id).toBe("resolved-image");
    expect(sendCalls()[1]).toEqual(sendCalls()[0]);
  });

  it.each(modes)("starts an explicit next %s send with a new key after acknowledgement", async (mode) => {
    mocks.post.mockResolvedValue({ data: receipt });
    const { result } = setup();
    await act(() => result.current[mode].mutateAsync(variables()));
    await act(() => result.current[mode].mutateAsync(variables()));
    expect(key(1)).not.toBe(key(0));
    expect(sendCalls()[1][1]).toEqual(sendCalls()[0][1]);
  });

  it("coalesces concurrent submit clicks into one upload and one request", async () => {
    let complete!: (value: { data: typeof receipt }) => void;
    mocks.post.mockImplementation((url: string) => url.endsWith("/welcome-media")
      ? Promise.resolve({ data: { media_id: "resolved-image" } })
      : new Promise((resolve) => { complete = resolve; }));
    const { result } = setup();
    const input = { ...variables(), image: new File(["image"], "photo.png") };
    let first!: Promise<unknown>;
    let second!: Promise<unknown>;
    act(() => {
      first = result.current.welcome.mutateAsync(input);
      second = result.current.welcome.mutateAsync(input);
    });
    await waitFor(() => expect(sendCalls()).toHaveLength(1));
    await act(async () => { complete({ data: receipt }); await Promise.all([first, second]); });
    expect(mocks.post).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["group", { groupId: "group-b" }],
    ["content", { messageContent: "A deliberate new message" }],
    ["audience", { recipientIds: ["person-c"] }],
    ["saved image", { headerImageId: "new-saved-image" }],
    ["passport introduction", { passportIntro: "A changed introduction" }],
    ["passport link", { passportLink: "https://example.test/upload/new" }],
    ["support contacts", { supportContactIds: ["support-b"] }],
  ])("starts a new reviewed identity after changing %s", async (_name, changed) => {
    mocks.post.mockRejectedValue(networkError);
    const { result } = setup();
    await act(async () => { await expect(result.current.passport.mutateAsync(variables())).rejects.toBe(networkError); });
    await approveChangedIntent(() => result.current.passport.mutateAsync({ ...variables(), ...changed }));
    expect(key(1)).not.toBe(key(0));
  });

  it.each([
    { audience: "not_submitted" as WhatsAppReminderAudience },
    { audienceClientGroupId: "client-group-b" },
  ])("starts a new reminder identity when its source or eligibility audience changes", async (changed) => {
    mocks.post.mockRejectedValue(networkError);
    const { result } = setup();
    await act(async () => { await expect(result.current.reminder.mutateAsync(variables())).rejects.toBe(networkError); });
    await approveChangedIntent(() => result.current.reminder.mutateAsync({ ...variables(), ...changed }));
    expect(key(1)).not.toBe(key(0));
  });

  it("starts a new invitation identity for a changed group invite link", async () => {
    mocks.post.mockRejectedValue(networkError);
    const { result } = setup();
    await act(async () => { await expect(result.current.invite.mutateAsync(variables())).rejects.toBe(networkError); });
    await approveChangedIntent(() => result.current.invite.mutateAsync({ ...variables(), groupInviteLink: "https://chat.whatsapp.com/NewInvite" }));
    expect(key(1)).not.toBe(key(0));
  });

  it("starts a new media identity for a replacement File even with the same filename", async () => {
    let uploads = 0;
    mocks.post.mockImplementation(async (url: string) => {
      if (url.endsWith("/welcome-media")) return { data: { media_id: `resolved-image-${++uploads}` } };
      throw networkError;
    });
    const { result } = setup();
    for (const bytes of ["old", "new"]) {
      const input = { ...variables(), image: new File([bytes], "photo.png") };
      await approveChangedIntent(() => result.current.welcome.mutateAsync(input));
    }
    expect(uploads).toBe(2);
    expect(key(1)).not.toBe(key(0));
    expect(sendCalls()[1][1].header_image_id).not.toBe(sendCalls()[0][1].header_image_id);
  });

  it("keeps the reviewed audience stable when only recipient order changes", async () => {
    mocks.post.mockRejectedValue(networkError);
    const { result } = setup();
    const input = variables();
    await act(async () => { await expect(result.current.reminder.mutateAsync(input)).rejects.toBe(networkError); });
    await act(async () => { await expect(result.current.reminder.mutateAsync({ ...input, recipientIds: [...input.recipientIds].reverse() })).rejects.toBe(networkError); });
    expect(sendCalls()[1]).toEqual(sendCalls()[0]);
    expect(input.recipientIds).toEqual(["person-b", "person-a"]);
  });

  it.each([{ id: "user-b", agency_id: "agency-a" }, { id: "user-a", agency_id: "agency-b" }])("separates reviewed intents when the actor or agency changes", async (actor) => {
    mocks.post.mockRejectedValue(networkError);
    const { result } = setup();
    await act(async () => { await expect(result.current.reminder.mutateAsync(variables())).rejects.toBe(networkError); });
    mocks.actor = actor;
    await act(async () => { await expect(result.current.reminder.mutateAsync(variables())).rejects.toBe(networkError); });
    expect(key(1)).not.toBe(key(0));
  });

  it("retries a failed upload before any send has occurred", async () => {
    mocks.post.mockRejectedValueOnce(new Error("Upload interrupted"))
      .mockResolvedValueOnce({ data: { media_id: "resolved-image" } }).mockResolvedValue({ data: receipt });
    const { result } = setup();
    const input = { ...variables(), image: new File(["image"], "photo.png") };
    await act(async () => { await expect(result.current.welcome.mutateAsync(input)).rejects.toThrow("Upload interrupted"); });
    expect(sendCalls()).toHaveLength(0);
    await act(() => result.current.welcome.mutateAsync(input));
    expect(sendCalls()).toHaveLength(1);
    expect(sendCalls()[0][1].header_image_id).toBe("resolved-image");
  });

  it("does not report an acknowledged send as failed when the cache refresh fails", async () => {
    mocks.post.mockResolvedValue({ data: receipt });
    const { result, client } = setup();
    vi.spyOn(client, "invalidateQueries").mockRejectedValue(new Error("Refresh failed"));
    await act(async () => { expect(await result.current.reminder.mutateAsync(variables())).toEqual(receipt); });
    expect(sendCalls()).toHaveLength(1);
  });

  it.each(modes)("recovers the same %s key after a full hook remount", async (mode) => {
    mocks.post.mockRejectedValueOnce(networkError).mockResolvedValue({ data: receipt });
    const first = setup();
    await act(async () => { await expect(first.result.current[mode].mutateAsync(variables())).rejects.toBe(networkError); });
    first.unmount();
    const restored = setup();
    await act(() => restored.result.current[mode].mutateAsync(variables()));
    expect(sendCalls()[1]).toEqual(sendCalls()[0]);
  });

  it("recovers uploaded media from matching bytes after remount without uploading again", async () => {
    let sends = 0;
    mocks.post.mockImplementation(async (url: string) => {
      if (url.endsWith("/welcome-media")) return { data: { media_id: "retained-image" } };
      if (++sends === 1) throw networkError;
      return { data: receipt };
    });
    const first = setup();
    await act(async () => { await expect(first.result.current.invite.mutateAsync({ ...variables(), image: new File(["same image bytes"], "photo.png", { type: "image/png" }) })).rejects.toBe(networkError); });
    first.unmount();
    const restored = setup();
    await act(() => restored.result.current.invite.mutateAsync({ ...variables(), image: new File(["same image bytes"], "photo.png", { type: "image/png" }) }));
    expect(sendCalls()[1]).toEqual(sendCalls()[0]);
    expect(mocks.post.mock.calls.filter(([url]) => String(url).endsWith("/welcome-media"))).toHaveLength(1);
  });

  it("blocks a lost photo or changed defaults after refresh until an explicit separate-send choice", async () => {
    mocks.post.mockImplementation(async (url: string) => {
      if (url.endsWith("/welcome-media")) return { data: { media_id: "retained-image" } };
      throw networkError;
    });
    const first = setup();
    await act(async () => { await expect(first.result.current.welcome.mutateAsync({ ...variables(), image: new File(["bytes"], "photo.png") })).rejects.toBe(networkError); });
    first.unmount();
    const restored = setup();
    let retainedError!: UncertainWhatsAppSendError;
    await act(async () => {
      try { await restored.result.current.welcome.mutateAsync(variables()); }
      catch (cause) { retainedError = cause as UncertainWhatsAppSendError; }
    });
    expect(retainedError).toBeInstanceOf(UncertainWhatsAppSendError);
    expect(sendCalls()).toHaveLength(1);
    retainedError.startNew();
    expect(sendCalls()).toHaveLength(1);
    await act(async () => { await expect(restored.result.current.welcome.mutateAsync(variables())).rejects.toBe(networkError); });
    expect(key(1)).not.toBe(key(0));
  });

  it("retains uncertain keys without expiring them into a new send", async () => {
    mocks.post.mockRejectedValue(networkError);
    const first = setup();
    await act(async () => { await expect(first.result.current.reminder.mutateAsync(variables())).rejects.toBe(networkError); });
    first.unmount();
    const time = vi.spyOn(Date, "now").mockReturnValue(Date.now() + 365 * 24 * 60 * 60 * 1000);
    try {
      const restored = setup();
      await act(async () => { await expect(restored.result.current.reminder.mutateAsync(variables())).rejects.toBe(networkError); });
      expect(sendCalls()[1]).toEqual(sendCalls()[0]);
    } finally { time.mockRestore(); }
  });

  it("stores no plaintext draft, audience, account identity or file bytes", async () => {
    mocks.post.mockRejectedValue(networkError);
    const { result } = setup();
    await act(async () => { await expect(result.current.passport.mutateAsync(variables())).rejects.toBe(networkError); });
    const storageKey = window.sessionStorage.key(0)!;
    const raw = window.sessionStorage.getItem(storageKey)!;
    expect(storageKey).toMatch(new RegExp(`^${NORMAL_SEND_STORAGE_PREFIX}[a-f0-9]{64}$`));
    expect(Object.keys(JSON.parse(raw)).sort()).toEqual(["draftHash", "key", "mediaId", "payloadHash", "state", "version"]);
    for (const privateValue of ["Reviewed message", "person-a", "person-b", "group-a", "user-a", "agency-a", "example.test", "support-a", "Upload your passport"]) {
      expect(storageKey + raw).not.toContain(privateValue);
    }
  });

  it.each(["getItem", "setItem"] as const)("blocks before any network call when session storage %s fails", async (method) => {
    const storage = vi.spyOn(Storage.prototype, method).mockImplementation(() => { throw new DOMException("Storage unavailable"); });
    try {
      const { result } = setup();
      await act(async () => { await expect(result.current.reminder.mutateAsync(variables())).rejects.toThrow(/session storage/); });
      expect(mocks.post).not.toHaveBeenCalled();
    } finally { storage.mockRestore(); }
  });

  it("does not silently replace a corrupt recovery record", async () => {
    mocks.post.mockRejectedValue(networkError);
    const first = setup();
    await act(async () => { await expect(first.result.current.reminder.mutateAsync(variables())).rejects.toBe(networkError); });
    first.unmount();
    window.sessionStorage.setItem(window.sessionStorage.key(0)!, "{corrupt");
    const restored = setup();
    await act(async () => { await expect(restored.result.current.reminder.mutateAsync(variables())).rejects.toThrow("previous send recovery record cannot be read"); });
    expect(sendCalls()).toHaveLength(1);
  });

  it("does not recreate account-cleared records when an in-flight upload finishes", async () => {
    let finishUpload!: (value: { data: { media_id: string } }) => void;
    mocks.post.mockImplementation(() => new Promise((resolve) => { finishUpload = resolve; }));
    const { result } = setup();
    let operation!: Promise<unknown>;
    act(() => { operation = result.current.welcome.mutateAsync({ ...variables(), image: new File(["image"], "photo.png") }); });
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    window.sessionStorage.clear();
    mocks.actor = { id: "different-user", agency_id: "agency-a" };
    await act(async () => {
      finishUpload({ data: { media_id: "late-upload" } });
      await expect(operation).rejects.toThrow("Your account changed");
    });
    expect(sendCalls()).toHaveLength(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("keeps the original key if acknowledgement persistence fails after a known receipt", async () => {
    mocks.post.mockResolvedValue({ data: receipt });
    const write = Storage.prototype.setItem;
    const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, name, value) {
      if (String(value).includes('"state":"acknowledged"')) throw new Error("Storage full");
      write.call(this, name, value);
    });
    try {
      const first = setup();
      await act(async () => { expect(await first.result.current.reminder.mutateAsync(variables())).toEqual(receipt); });
      first.unmount();
      const restored = setup();
      await act(() => restored.result.current.reminder.mutateAsync(variables()));
      expect(sendCalls()[1]).toEqual(sendCalls()[0]);
    } finally { storage.mockRestore(); }
  });

  it("refuses changed direct API payloads under a bound identity without including private values", async () => {
    const intent = new WhatsAppSendIntent();
    await intent.bind("group-a", { message_content: "private first draft" });
    await expect(intent.bind("group-a", { message_content: "private changed draft" })).rejects.toThrow("The reviewed send changed.");
    await expect(intent.bind("group-b", { message_content: "private first draft" })).rejects.toThrow("The reviewed send changed.");
    await expect(intent.bind("group-a", { message_content: "private first draft" })).resolves.toBeUndefined();
  });
});
