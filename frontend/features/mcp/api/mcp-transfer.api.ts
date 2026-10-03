export interface McpFileTransfer {
  id: string;
  kind: "upload_workbook" | "upload_pdf" | "download";
  purpose: "contact_broadcast" | "group_workbook" | "document_pdf" | "export";
  status: "pending" | "transferring" | "completed" | "failed";
  filename: string;
  media_type: string;
  byte_size: number;
  sha256: string;
  expires_at: string;
  agency_id: string | null;
  group_id: string | null;
  destination_label?: string | null;
  document_type?: string | null;
  download_completed: boolean;
  delivered: boolean;
}

export class McpTransferError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

async function transferFetch(id: string, token: string, suffix = "", options: RequestInit = {}) {
  const response = await fetch(`/mcp/native-transfers/${encodeURIComponent(id)}${suffix}`, {
    ...options, credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer",
    headers: { ...options.headers, Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new McpTransferError(response.status,
    response.status === 403 || response.status === 404 ? "This transfer has expired or is no longer allowed. Ask your app for a new transfer link."
      : response.status === 409 ? "This transfer is already being used. Check its status before trying again."
        : response.status === 422 ? "The file could not be accepted. Ask your app to prepare a new transfer."
          : "The transfer could not be completed. Check your connection and try again.");
  return response;
}

export const mcpTransferApi = {
  status: async (id: string, token: string, signal?: AbortSignal): Promise<McpFileTransfer> =>
    (await transferFetch(id, token, "", { signal })).json(),
  download: (id: string, token: string, signal?: AbortSignal) => transferFetch(id, token, "/content", { signal }),
  upload: async (ticket: McpFileTransfer, token: string, file: Blob, signal?: AbortSignal): Promise<McpFileTransfer> =>
    (await transferFetch(ticket.id, token, "/content", { method: "PUT", body: file, signal, headers: { "Content-Type": ticket.media_type } })).json(),
  acknowledge: async (ticket: McpFileTransfer, token: string): Promise<McpFileTransfer> =>
    (await transferFetch(ticket.id, token, "/delivery", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ byte_size: ticket.byte_size, sha256: ticket.sha256 }) })).json(),
};
