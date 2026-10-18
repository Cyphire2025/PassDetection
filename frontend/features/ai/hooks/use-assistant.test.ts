import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assistantApi } from "../api";
import { useAssistant } from "./use-assistant";

vi.mock("../api", () => ({ assistantApi: { status: vi.fn(), live: vi.fn(), conversation: vi.fn(), deleteConversation: vi.fn() }, assistantMessage: (_: unknown, fallback: string) => fallback }));

const status = { configured: true, speech_configured: true, model: "gemini-3.8-flash", reasoning_effort: "medium", name: "Synthetic administrator", account_id: "owner-a", account_scope: "super_admin", access: "read_only" as const };
const answer = vi.fn(), image = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(assistantApi.status).mockResolvedValue(status);
  vi.mocked(assistantApi.live).mockResolvedValue({ observed_at: "2026-10-19T00:00:00Z", agencies: [] });
  vi.mocked(assistantApi.conversation).mockImplementation(async (id) => ({ items: [{ id: `turn-${id}`, user: `Question ${id}`, assistant: `Answer ${id}`, created_at: "2026-10-19T00:00:00Z" }], next_cursor: null }));
  vi.mocked(assistantApi.deleteConversation).mockResolvedValue(undefined);
});
afterEach(cleanup);

async function activeChat() {
  const hook = renderHook(() => useAssistant(answer, image));
  await waitFor(() => expect(hook.result.current.access).toBe("ready"));
  await act(async () => { await hook.result.current.openConversation("a"); });
  return hook;
}

describe("private conversation deletion", () => {
  it("clears the selected chat only after deletion succeeds", async () => {
    const { result } = await activeChat();
    await act(async () => { expect(await result.current.deleteConversation("a")).toBe(true); });
    expect(assistantApi.deleteConversation).toHaveBeenCalledWith("a");
    expect(result.current.conversationId).toBeNull();
    expect(result.current.messages).toEqual([]);
  });

  it("keeps the chat available for retry after a storage failure", async () => {
    const { result } = await activeChat();
    vi.mocked(assistantApi.deleteConversation).mockRejectedValueOnce(new Error("Retry deletion"));
    await act(async () => { await expect(result.current.deleteConversation("a")).rejects.toThrow("Retry deletion"); });
    expect(result.current.conversationId).toBe("a");
    expect(result.current.messages.at(-1)?.text).toBe("Answer a");
  });

  it("does not clear another conversation opened while deletion is pending", async () => {
    const { result } = await activeChat();
    let finish!: () => void;
    vi.mocked(assistantApi.deleteConversation).mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
    const deletion = result.current.deleteConversation("a");
    await act(async () => { await result.current.openConversation("b"); });
    await act(async () => { finish(); expect(await deletion).toBe(false); });
    expect(result.current.conversationId).toBe("b");
    expect(result.current.messages.at(-1)?.text).toBe("Answer b");
  });

  it("does not clear a different account after its status refreshes", async () => {
    const { result } = await activeChat();
    let finish!: () => void;
    vi.mocked(assistantApi.deleteConversation).mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
    const deletion = result.current.deleteConversation("a");
    vi.mocked(assistantApi.status).mockResolvedValue({ ...status, account_id: "owner-b" });
    await act(async () => { await result.current.refresh(); });
    await act(async () => { await result.current.openConversation("b"); });
    await act(async () => { finish(); expect(await deletion).toBe(false); });
    expect(result.current.status?.account_id).toBe("owner-b");
    expect(result.current.conversationId).toBe("b");
  });
});
