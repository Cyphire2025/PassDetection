import { afterEach, expect, it, vi } from "vitest";
import { mcpTransferApi, type McpFileTransfer } from "./mcp-transfer.api";

const token = `gcmcp_transfer_${"a".repeat(48)}`;
const ticket = { id: "ticket/a", media_type: "application/pdf", byte_size: 19, sha256: "f".repeat(64) } as McpFileTransfer;
afterEach(() => vi.unstubAllGlobals());
it("uses only the limited credential and prevents cookies, redirects, referrers and caching for every transfer lane", async () => {
  const fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify(ticket), { headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  await mcpTransferApi.status(ticket.id, token);
  await mcpTransferApi.download(ticket.id, token);
  await mcpTransferApi.upload(ticket, token, new Blob(["bytes"]));
  await mcpTransferApi.acknowledge(ticket, token);
  for (const [url, options] of fetch.mock.calls) {
    expect(url).not.toContain(token);
    expect(options).toMatchObject({ credentials: "omit", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer", headers: { Authorization: `Bearer ${token}` } });
  }
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["/mcp/native-transfers/ticket%2Fa", "/mcp/native-transfers/ticket%2Fa/content", "/mcp/native-transfers/ticket%2Fa/content", "/mcp/native-transfers/ticket%2Fa/delivery"]);
  expect(fetch.mock.calls[2][1]).toMatchObject({ method: "PUT", headers: { "Content-Type": "application/pdf" } });
  expect(JSON.parse(fetch.mock.calls[3][1].body)).toEqual({ byte_size: ticket.byte_size, sha256: ticket.sha256 });
});
it("reports bounded errors without rendering a sensitive server response body", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("private server details", { status: 403 })));
  await expect(mcpTransferApi.status(ticket.id, token)).rejects.toThrow("expired or is no longer allowed");
});
