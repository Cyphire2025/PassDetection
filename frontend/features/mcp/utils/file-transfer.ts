import type { McpFileTransfer } from "../api/mcp-transfer.api";

export const MCP_TRANSFER_ID = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export const MAX_BROWSER_TRANSFER_BYTES = 128 * 1024 * 1024;
const FILE_TYPES: Record<string, string> = {
  xlsx: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", pdf: "application/pdf",
  png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", zip: "application/zip", csv: "text/csv",
};

export function captureTransferToken() {
  const fragment = window.location.hash;
  if (fragment || window.location.search) window.history.replaceState(null, "", window.location.pathname);
  const values = new URLSearchParams(fragment.slice(1));
  if ([...values.keys()].length !== 1 || values.getAll("token").length !== 1) return null;
  const token = values.get("token");
  return token && /^gcmcp_transfer_[A-Za-z0-9_-]{32,128}$/.test(token) ? token : null;
}

function fileExtension(name: string) { return name.split(".").at(-1)?.toLowerCase() ?? ""; }

export function validTransfer(ticket: McpFileTransfer, id: string) {
  if (!ticket || ticket.id !== id || !MCP_TRANSFER_ID.test(id)
    || !["upload_workbook", "upload_pdf", "download"].includes(ticket.kind)
    || !["contact_broadcast", "group_workbook", "document_pdf", "export"].includes(ticket.purpose)
    || !["pending", "transferring", "completed", "failed"].includes(ticket.status)
    || typeof ticket.filename !== "string" || !ticket.filename || ticket.filename.length > 255
    || /[\\/<>:"|?*\u0000-\u001f]/.test(ticket.filename) || /^[. ]|[. ]$/.test(ticket.filename)
    || /^(con|prn|aux|nul|com[1-9]|lpt[1-9])\./i.test(ticket.filename)
    || FILE_TYPES[fileExtension(ticket.filename)] !== ticket.media_type
    || !Number.isSafeInteger(ticket.byte_size) || ticket.byte_size <= 0 || ticket.byte_size > MAX_BROWSER_TRANSFER_BYTES
    || typeof ticket.sha256 !== "string" || !/^[a-f0-9]{64}$/i.test(ticket.sha256)
    || !Number.isFinite(Date.parse(ticket.expires_at))
    || !(ticket.agency_id === null || typeof ticket.agency_id === "string" && MCP_TRANSFER_ID.test(ticket.agency_id))
    || !(ticket.group_id === null || typeof ticket.group_id === "string" && MCP_TRANSFER_ID.test(ticket.group_id))
    || typeof ticket.download_completed !== "boolean" || typeof ticket.delivered !== "boolean") return false;
  if ((ticket.destination_label != null && (typeof ticket.destination_label !== "string" || ticket.destination_label.length > 200))
    || (ticket.document_type != null && (typeof ticket.document_type !== "string" || ticket.document_type.length > 80))) return false;
  if (ticket.kind === "upload_workbook") return ticket.media_type === FILE_TYPES.xlsx && ["group_workbook", "contact_broadcast"].includes(ticket.purpose);
  if (ticket.kind === "upload_pdf") return ticket.media_type === FILE_TYPES.pdf && ticket.purpose === "document_pdf";
  return ticket.purpose === "export";
}

export function samePreparedTransfer(left: McpFileTransfer, right: McpFileTransfer) {
  return ["id", "kind", "purpose", "filename", "media_type", "byte_size", "sha256", "expires_at", "agency_id", "group_id", "document_type"]
    .every((key) => left[key as keyof McpFileTransfer] === right[key as keyof McpFileTransfer]);
}

export async function verifyTransferBytes(blob: Blob, ticket: McpFileTransfer) {
  if (blob.size !== ticket.byte_size) throw new Error("This file’s size does not match the prepared transfer.");
  const bytes = await blob.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hash = [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
  if (hash.toLowerCase() !== ticket.sha256.toLowerCase()) throw new Error("This file does not match the prepared transfer.");
}

export async function verifySelectedFile(file: File, ticket: McpFileTransfer) {
  const extension = ticket.kind === "upload_workbook" ? "xlsx" : "pdf";
  if (fileExtension(file.name) !== extension || (file.type && file.type.toLowerCase() !== ticket.media_type))
    throw new Error(`Choose the prepared ${extension.toUpperCase()} file for this transfer.`);
  await verifyTransferBytes(file, ticket);
}

function attachmentFilename(header: string | null) {
  if (!header || header.length > 2048 || !/^attachment(?:\s*;|$)/i.test(header)) return null;
  const extended = [...header.matchAll(/(?:^|;)\s*filename\*\s*=\s*UTF-8''([^;]+)/gi)];
  const basic = [...header.matchAll(/(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;]+))/gi)];
  if (extended.length > 1 || basic.length > 1) return null;
  try { return extended.length === 1 ? decodeURIComponent(extended[0][1].trim()) : basic.length === 1 ? (basic[0][1] ?? basic[0][2]).trim() : null; }
  catch { return null; }
}

export async function verifiedDownload(response: Response, ticket: McpFileTransfer): Promise<Blob> {
  if (response.headers.get("Content-Type")?.split(";")[0].trim().toLowerCase() !== ticket.media_type
    || attachmentFilename(response.headers.get("Content-Disposition")) !== ticket.filename)
    throw new Error("The returned file did not match this transfer. Ask your app for a new link.");
  const reader = response.body?.getReader();
  if (!reader) throw new Error("The file could not be read. Try the download again.");
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > ticket.byte_size) throw new Error("The returned file is larger than this transfer allows.");
      chunks.push(new Uint8Array(value));
    }
  } catch (error) { await reader.cancel().catch(() => undefined); throw error; }
  const blob = new Blob(chunks, { type: ticket.media_type });
  await verifyTransferBytes(blob, ticket);
  return blob;
}
