import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assistantApi } from "../api";
import { useAssistant } from "./use-assistant";
import { rememberedConversation, rememberConversation } from "../last-conversation";

vi.mock("../api", () => ({ assistantApi: { status: vi.fn(), live: vi.fn(), conversation: vi.fn(), deleteConversation: vi.fn(), stream: vi.fn() }, assistantMessage: (_: unknown, fallback: string) => fallback }));

const status = { configured: true, speech_configured: true, model: "gemini-3.8-flash", reasoning_effort: "medium", name: "Synthetic administrator", account_id: "owner-a", account_scope: "super_admin", access: "read_only" as const };
const answer = vi.fn(), image = vi.fn();

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(assistantApi.status).mockResolvedValue(status);
  vi.mocked(assistantApi.live).mockResolvedValue({ observed_at: "2026-10-19T00:00:00Z", mcp: { connected: true, available_tools: 8, write_enabled: false } });
  vi.mocked(assistantApi.conversation).mockImplementation(async (id) => ({ items: [{ id: `turn-${id}`, user: `Question ${id}`, assistant: `Answer ${id}`, created_at: "2026-10-19T00:00:00Z" }], next_cursor: null }));
  vi.mocked(assistantApi.deleteConversation).mockResolvedValue(undefined);
});

describe("last conversation on this device", () => {
  const saved = "b6c548e0-6e77-4d1b-b107-6799b9d31201";
  it("restores an opaque ID only after the same owner is authenticated", async () => {
    rememberConversation("owner-a:super_admin", saved);
    const { result } = renderHook(() => useAssistant(answer, image));
    await waitFor(() => expect(result.current.conversationId).toBe(saved));
    expect(assistantApi.conversation).toHaveBeenCalledWith(saved);
    expect(result.current.messages.at(-1)?.text).toBe(`Answer ${saved}`);
    expect(localStorage.getItem("gc:ai:last-conversation:v1:owner-a:super_admin")).toBe(saved);
    expect(localStorage.getItem("gc:ai:last-conversation:v1:owner-a:super_admin")).not.toContain("Answer");
  });
  it("does not restore a different account's remembered chat", async () => {
    rememberConversation("owner-b:super_admin", saved);
    const { result } = renderHook(() => useAssistant(answer, image));
    await waitFor(() => expect(result.current.access).toBe("ready"));
    expect(result.current.conversationId).toBeNull();
    expect(assistantApi.conversation).not.toHaveBeenCalled();
  });
  it("forgets a deleted chat and starts fresh without returning old captions", async () => {
    rememberConversation("owner-a:super_admin", saved);
    vi.mocked(assistantApi.conversation).mockRejectedValueOnce({ status: 410 });
    const { result } = renderHook(() => useAssistant(answer, image));
    await waitFor(() => expect(rememberedConversation("owner-a:super_admin")).toBeNull());
    expect(result.current.messages).toEqual([]);
    expect(result.current.conversationId).toBeNull();
  });
  it("does not overwrite a new chat with a late restoration response", async () => {
    rememberConversation("owner-a:super_admin", saved);
    let complete!: (value: Awaited<ReturnType<typeof assistantApi.conversation>>) => void;
    vi.mocked(assistantApi.conversation).mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
    const { result } = renderHook(() => useAssistant(answer, image));
    await waitFor(() => expect(assistantApi.conversation).toHaveBeenCalled());
    act(() => result.current.newConversation());
    await act(async () => { complete({ items: [{ id: "old", user: "Old question", assistant: "Old answer", created_at: "2026-10-19T00:00:00Z" }], next_cursor: null }); });
    expect(result.current.messages).toEqual([]);
    expect(result.current.conversationId).toBeNull();
  });
});
afterEach(cleanup);

describe("workspace MCP status", () => {
  it("preserves a disconnected MCP result despite a successful timestamp", async () => {
    vi.mocked(assistantApi.live).mockResolvedValue({ observed_at: "2026-10-19T00:00:00Z", mcp: { connected: false, code: "mcp_no_tools", message: "No workspace tools are currently available." } });
    const { result } = renderHook(() => useAssistant(answer, image));
    await waitFor(() => expect(result.current.mcpAccess?.connected).toBe(false));
    expect(result.current.observedAt).not.toBeNull();
    expect(result.current.mcpAccess?.code).toBe("mcp_no_tools");
    expect(result.current.access).toBe("ready");
  });
  it("keeps general chat available after a failed MCP check and recovers on refresh", async () => {
    vi.mocked(assistantApi.live).mockRejectedValueOnce(new Error("offline"));
    const { result } = renderHook(() => useAssistant(answer, image));
    await waitFor(() => expect(result.current.mcpAccess?.code).toBe("mcp_status_unavailable"));
    expect(result.current.access).toBe("ready");
    expect(result.current.observedAt).toBeNull();
    await act(async () => { await result.current.refresh(); });
    expect(result.current.mcpAccess).toMatchObject({ connected: true, available_tools: 8 });
  });
  it("still clears authenticated access when the MCP check reports an expired session", async () => {
    vi.mocked(assistantApi.live).mockRejectedValueOnce({ status: 401 });
    const { result } = renderHook(() => useAssistant(answer, image));
    await waitFor(() => expect(result.current.access).toBe("guest"));
    expect(result.current.status).toBeNull();
    expect(result.current.mcpAccess).toBeNull();
  });
  it.each(["success", "authentication failure"])("ignores an older refresh %s after a newer denial", async (outcome) => {
    let resolve!: (value: Awaited<ReturnType<typeof assistantApi.live>>) => void;
    let reject!: (cause: unknown) => void;
    vi.mocked(assistantApi.live).mockImplementationOnce(() => new Promise((done, fail) => { resolve = done; reject = fail; }));
    const { result } = renderHook(() => useAssistant(answer, image));
    await waitFor(() => expect(assistantApi.live).toHaveBeenCalledOnce());
    vi.mocked(assistantApi.live).mockResolvedValueOnce({ observed_at: "2026-10-19T00:00:01Z", mcp: { connected: false, code: "mcp_access_denied" } });
    await act(async () => { await result.current.refresh(); });
    await act(async () => {
      if (outcome === "success") resolve({ observed_at: "2026-10-19T00:00:00Z", mcp: { connected: true } });
      else reject({ status: 401 });
    });
    expect(result.current.mcpAccess).toMatchObject({ connected: false, code: "mcp_access_denied" });
    expect(result.current.observedAt).toBe("2026-10-19T00:00:01Z");
    expect(result.current.access).toBe("ready");
  });
});

it("surfaces a failed streamed answer outside the collapsed conversation", async () => {
  vi.mocked(assistantApi.stream).mockImplementation(async (_input, _signal, receive) => { receive({ type: "error", code: "provider_configuration", message: "Check your AI connection." }); });
  const { result } = renderHook(() => useAssistant(answer, image));
  await waitFor(() => expect(result.current.access).toBe("ready"));
  await act(async () => { await result.current.send("A synthetic question"); });
  expect(result.current.error).toBe("Check your AI connection.");
  expect(result.current.messages.at(-1)?.error).toBe("Check your AI connection.");
  expect(result.current.busy).toBe(false);
  expect(answer).not.toHaveBeenCalled();
});

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
