import { Blob as NodeBlob, File as NodeFile } from "node:buffer";
import { createHash, webcrypto } from "node:crypto";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { captureTransferToken, MAX_BROWSER_TRANSFER_BYTES, samePreparedTransfer, validTransfer, verifiedDownload, verifySelectedFile } from "./file-transfer";
import type { McpFileTransfer } from "../api/mcp-transfer.api";

const id = "00000000-0000-4000-8000-000000000021";
const bytes = Buffer.from("prepared file bytes");
function ticket(overrides: Partial<McpFileTransfer> = {}): McpFileTransfer {
  return { id, kind: "download", purpose: "export", status: "pending", filename: "Passenger report.pdf", media_type: "application/pdf",
    byte_size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"), expires_at: "2099-10-03T00:10:00Z",
    agency_id: null, group_id: null, download_completed: false, delivered: false, ...overrides };
}
beforeEach(() => { vi.stubGlobal("Blob", NodeBlob); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

it("captures only the fragment credential and removes it from history before use", () => {
  const token = `gcmcp_transfer_${"a".repeat(48)}`;
  window.history.replaceState({ token }, "", `/mcp/file-transfer/${id}?unexpected=value#token=${token}`);
  expect(captureTransferToken()).toBe(token);
  expect(window.location.hash).toBe(""); expect(window.location.href).not.toContain(token);
  expect(window.location.search).toBe(""); expect(window.history.state).toBeNull();
  expect(captureTransferToken()).toBeNull();
});
it.each(["token=bad", "token=gcmcp_transfer_" + "a".repeat(48) + "&other=value", "token=x&token=y"])("rejects malformed or duplicate fragments %s and removes them", (fragment) => {
  window.history.replaceState(null, "", `/mcp/file-transfer/${id}#${fragment}`);
  expect(captureTransferToken()).toBeNull(); expect(window.location.hash).toBe("");
});
it.each([
  { filename: "../report.pdf" }, { filename: "CON.pdf" }, { filename: "report.exe", media_type: "application/pdf" },
  { byte_size: MAX_BROWSER_TRANSFER_BYTES + 1 }, { sha256: "invalid" }, { expires_at: "invalid" }, { purpose: "group_workbook" },
])("rejects unsafe or unbound transfer metadata %j", (values) => {
  expect(validTransfer(ticket(values as Partial<McpFileTransfer>), id)).toBe(false);
});
it("accepts safe Unicode output names while binding immutable metadata", () => {
  const value = ticket({ filename: "यात्री report.pdf" });
  expect(validTransfer(value, id)).toBe(true);
  expect(samePreparedTransfer(value, { ...value, status: "completed", download_completed: true })).toBe(true);
  expect(samePreparedTransfer(value, { ...value, byte_size: value.byte_size + 1 })).toBe(false);
  expect(samePreparedTransfer(value, { ...value, group_id: id })).toBe(false);
});
it("accepts a renamed exact upload and rejects different contents or a wrong file type before sending", async () => {
  const value = ticket({ kind: "upload_pdf", purpose: "document_pdf", filename: "normalized.pdf" });
  await expect(verifySelectedFile(new NodeFile([bytes], "Original name.pdf", { type: "application/pdf" }) as unknown as File, value)).resolves.toBeUndefined();
  await expect(verifySelectedFile(new NodeFile([Buffer.from("different file bytes")], "a.pdf", { type: "application/pdf" }) as unknown as File, value)).rejects.toThrow("size");
  await expect(verifySelectedFile(new NodeFile([Buffer.from("changed  file bytes")], "a.pdf", { type: "application/pdf" }) as unknown as File, value)).rejects.toThrow("does not match");
  await expect(verifySelectedFile(new NodeFile([bytes], "a.xlsx", { type: "application/pdf" }) as unknown as File, value)).rejects.toThrow("PDF");
});
it("verifies exact streamed download bytes and RFC5987 filename before creating a saveable file", async () => {
  const value = ticket({ filename: "यात्री report.pdf" });
  const response = new Response(bytes, { headers: { "Content-Type": "application/pdf", "Content-Disposition": `attachment; filename*=UTF-8''${encodeURIComponent(value.filename)}` } });
  const file = await verifiedDownload(response, value);
  expect(file.size).toBe(bytes.length); expect(Buffer.from(await file.arrayBuffer())).toEqual(bytes);
});
it.each([
  { "Content-Type": "text/html", "Content-Disposition": "attachment; filename=\"Passenger report.pdf\"" },
  { "Content-Type": "application/pdf", "Content-Disposition": "inline; filename=\"Passenger report.pdf\"" },
  { "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=\"another.pdf\"" },
  { "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=\"Passenger report.pdf\"; filename=\"Passenger report.pdf\"" },
])("rejects wrong content type or attachment filename %j", async (headers) => {
  await expect(verifiedDownload(new Response(bytes, { headers }), ticket())).rejects.toThrow("did not match");
});
it("cancels an oversized stream and refuses equal-size checksum corruption", async () => {
  const headers = { "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=\"Passenger report.pdf\"" };
  await expect(verifiedDownload(new Response(Buffer.concat([bytes, bytes]), { headers }), ticket())).rejects.toThrow("larger");
  await expect(verifiedDownload(new Response(Buffer.alloc(bytes.length, 1), { headers }), ticket())).rejects.toThrow("does not match");
});
