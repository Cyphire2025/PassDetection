import { Blob as NodeBlob, File as NodeFile } from "node:buffer";
import { createHash, webcrypto } from "node:crypto";
import { StrictMode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { McpFileTransfer } from "../api/mcp-transfer.api";
import { useMcpFileTransfer } from "./use-mcp-file-transfer";

const id = "00000000-0000-4000-8000-000000000021";
const token = `gcmcp_transfer_${"a".repeat(48)}`;
const bytes = Buffer.from("prepared local file");
const contentHeaders = { "Content-Type": "application/pdf", "Content-Disposition": 'attachment; filename="report.pdf"' };
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
function metadata(upload: boolean): McpFileTransfer {
  return { id, kind: upload ? "upload_pdf" : "download", purpose: upload ? "document_pdf" : "export", status: "pending", filename: "report.pdf", media_type: "application/pdf", byte_size: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"), expires_at: "2099-10-03T00:10:00Z", agency_id: null, group_id: null, download_completed: false, delivered: false };
}
function setup(upload = false, content?: Response) {
  const ticket = metadata(upload);
  const fetch = vi.fn(async (url: string, options: RequestInit = {}) => {
    if (url.endsWith("/content") && options.method !== "PUT") return content ?? new Response(bytes, { headers: contentHeaders });
    return new Response(JSON.stringify({ ...ticket, status: options.method === "PUT" ? "completed" : "pending", delivered: options.method === "POST", download_completed: options.method === "POST" }), { headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetch);
  window.history.replaceState(null, "", `/mcp/file-transfer/${id}#token=${token}`);
  const hook = renderHook(() => useMcpFileTransfer(id), { wrapper: StrictMode });
  return { ...hook, fetch };
}
async function ready(context: ReturnType<typeof setup>) {
  await waitFor(() => expect(context.result.current.loading).toBe(false));
  expect(context.result.current.ticket?.id).toBe(id);
}
async function prepared(context: ReturnType<typeof setup>) {
  await ready(context);
  await act(async () => { await context.result.current.prepare(); });
  expect(context.result.current.download?.size).toBe(bytes.length);
}
beforeEach(() => { vi.stubGlobal("Blob", NodeBlob); vi.stubGlobal("crypto", webcrypto); });
afterEach(() => {
  cleanup();
  delete (window as Window & { showSaveFilePicker?: unknown }).showSaveFilePicker;
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

it("does not dispatch an upload after its local hash read outlives the transfer route", async () => {
  const context = setup(true);
  await ready(context);
  const read = deferred<ArrayBuffer>();
  const file = new NodeFile([bytes], "renamed.pdf", { type: "application/pdf" });
  const arrayBuffer = vi.spyOn(file, "arrayBuffer").mockReturnValue(read.promise);
  act(() => context.result.current.selectFile(file as unknown as File));
  let operation!: Promise<void>;
  act(() => { operation = context.result.current.upload(); });
  await waitFor(() => expect(arrayBuffer).toHaveBeenCalledOnce());
  context.unmount();
  read.resolve(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
  await act(async () => { await operation; });
  expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(0);
});

it("cancels a pending response reader when the route leaves", async () => {
  let release!: () => void;
  const cancel = vi.fn();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) { release = () => { if (!cancel.mock.calls.length) { controller.enqueue(bytes); controller.close(); } }; },
    cancel,
  });
  const context = setup(false, new Response(stream, { headers: contentHeaders }));
  await ready(context);
  let operation!: Promise<void>;
  act(() => { operation = context.result.current.prepare(); });
  await waitFor(() => expect(stream.locked).toBe(true));
  context.unmount();
  try { await waitFor(() => expect(cancel).toHaveBeenCalledOnce()); }
  finally { release(); await act(async () => { await operation; }); }
  expect(stream.locked).toBe(false);
});

it("does not open a writer or acknowledge after a departed route's file picker returns", async () => {
  const context = setup();
  await prepared(context);
  const picker = deferred<{ createWritable: ReturnType<typeof vi.fn> }>();
  const createWritable = vi.fn(async () => ({ write: vi.fn(), close: vi.fn() }));
  const showSaveFilePicker = vi.fn(() => picker.promise);
  Object.defineProperty(window, "showSaveFilePicker", { configurable: true, value: showSaveFilePicker });
  let operation!: Promise<void>;
  act(() => { operation = context.result.current.save(); });
  expect(showSaveFilePicker).toHaveBeenCalledOnce();
  context.unmount();
  picker.resolve({ createWritable });
  await act(async () => { await operation; });
  expect(createWritable).not.toHaveBeenCalled();
  expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
});

it("aborts the staged local writer and withholds delivery after navigation during write", async () => {
  const context = setup();
  await prepared(context);
  const written = deferred<void>();
  const write = vi.fn(() => written.promise);
  const close = vi.fn();
  const abort = vi.fn();
  Object.defineProperty(window, "showSaveFilePicker", { configurable: true, value: async () => ({ createWritable: async () => ({ write, close, abort }) }) });
  let operation!: Promise<void>;
  act(() => { operation = context.result.current.save(); });
  await waitFor(() => expect(write).toHaveBeenCalledOnce());
  context.unmount();
  written.resolve();
  await act(async () => { await operation; });
  expect(abort).toHaveBeenCalledOnce();
  expect(close).not.toHaveBeenCalled();
  expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
});

it("still uploads the exact prepared file on the same mounted route under StrictMode", async () => {
  const context = setup(true);
  await ready(context);
  act(() => context.result.current.selectFile(new NodeFile([bytes], "renamed.pdf", { type: "application/pdf" }) as unknown as File));
  await act(async () => { await context.result.current.upload(); });
  expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(1);
  expect(context.result.current.finished).toBe(true);
  expect(window.location.hash).toBe("");
});

it("still acknowledges a mounted route only after the selected writer closes", async () => {
  const context = setup();
  await prepared(context);
  const closed = deferred<void>();
  const close = vi.fn(() => closed.promise);
  Object.defineProperty(window, "showSaveFilePicker", { configurable: true, value: async () => ({ createWritable: async () => ({ write: vi.fn(), close }) }) });
  let operation!: Promise<void>;
  act(() => { operation = context.result.current.save(); });
  await waitFor(() => expect(close).toHaveBeenCalledOnce());
  expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
  closed.resolve();
  await act(async () => { await operation; });
  expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  expect(context.result.current.finished).toBe(true);
});

it("retains explicit user confirmation for the mounted anchor-download fallback", async () => {
  const context = setup();
  await prepared(context);
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = vi.fn(() => "blob:synthetic-transfer");
    static revokeObjectURL = vi.fn();
  });
  try {
    await act(async () => { await context.result.current.save(); });
    expect(click).toHaveBeenCalledOnce();
    expect(context.result.current.confirming).toBe(true);
    expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(0);
    await act(async () => { await context.result.current.confirmSave(); });
    expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
    expect(context.result.current.finished).toBe(true);
  } finally { click.mockRestore(); }
});

it("aborts an already-dispatched PUT without claiming the server rolled it back", async () => {
  const context = setup(true);
  await ready(context);
  const completed = deferred<Response>();
  const originalFetch = context.fetch.getMockImplementation()!;
  context.fetch.mockImplementation(async (url, options = {}) => options.method === "PUT" ? completed.promise : originalFetch(url, options));
  act(() => context.result.current.selectFile(new NodeFile([bytes], "renamed.pdf", { type: "application/pdf" }) as unknown as File));
  let operation!: Promise<void>;
  act(() => { operation = context.result.current.upload(); });
  await waitFor(() => expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(1));
  const request = context.fetch.mock.calls.find(([, options]) => options?.method === "PUT")![1];
  expect(request?.signal?.aborted).toBe(false);
  context.unmount();
  expect(request?.signal?.aborted).toBe(true);
  completed.resolve(new Response(JSON.stringify({ ...metadata(true), status: "completed" })));
  await act(async () => { await operation; });
  expect(context.fetch.mock.calls.filter(([, options]) => options?.method === "PUT")).toHaveLength(1);
});
