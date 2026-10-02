import { afterEach, expect, it, vi } from "vitest";
import { McpRequestError, mcpRequestApi } from "./mcp-request.api";

afterEach(() => vi.unstubAllGlobals());
it("uses the scoped requester cookie with no dashboard bearer credential or query secret", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "pending" }), { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  const signal = new AbortController().signal;
  await mcpRequestApi.status("request-a", signal);
  expect(fetcher).toHaveBeenCalledWith("/oauth/mcp/requests/request-a", expect.objectContaining({
    method: "GET", credentials: "include", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer", signal,
    headers: { "X-MCP-Request": "request-a" },
  }));
});
it("finalizes only with the bound request header and an empty JSON body", async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ redirect_url: "verified" }), { status: 200 }));
  vi.stubGlobal("fetch", fetcher); await mcpRequestApi.finalize("request-a");
  expect(fetcher).toHaveBeenCalledWith("/oauth/mcp/requests/request-a/finalize", expect.objectContaining({
    method: "POST", body: "{}", credentials: "include", headers: { "X-MCP-Request": "request-a", "Content-Type": "application/json" },
  }));
});
it.each([404, 409, 500])("does not expose response details or callback secrets on HTTP %s", async (status) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("secret-private-response", { status })));
  const error = await mcpRequestApi.status("request-a").catch((value: unknown) => value);
  expect(error).toBeInstanceOf(McpRequestError); expect((error as Error).message).not.toContain("secret-private-response");
});
