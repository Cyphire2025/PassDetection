import type { AxiosRequestConfig, RawAxiosResponseHeaders } from "axios";
import {
  SENSITIVE_STATE_RESET_EVENT,
  subscribeToSessionResets,
} from "@/features/auth/services/session-state";
import apiClient from "./client";

export const MAX_BOUNDED_DOWNLOAD_FALLBACK_BYTES = 32 * 1024 * 1024;
export const DOWNLOAD_HARD_TIMEOUT_MS = 10 * 60 * 1_000;
export const DOWNLOAD_IDLE_TIMEOUT_MS = 60_000;

interface FileDownloadWritable {
  write(data: Uint8Array): Promise<void>;
  close(): Promise<void>;
  abort?(reason?: unknown): Promise<void>;
}

interface FileDownloadHandle {
  createWritable(): Promise<FileDownloadWritable>;
}

interface FilePickerWindow extends Window {
  showSaveFilePicker?: (options: {
    suggestedName: string;
  }) => Promise<FileDownloadHandle>;
}

export interface StreamedDownloadRequest {
  url: string;
  method?: "GET" | "POST";
  params?: AxiosRequestConfig["params"];
  data?: AxiosRequestConfig["data"];
  suggestedFilename: string;
  signal?: AbortSignal;
  maxFallbackBytes?: number;
  validateHeaders?: (headers: RawAxiosResponseHeaders) => void;
}

export interface StreamedDownloadResult {
  filename: string;
  bytesWritten: number;
  delivery: "file-system" | "bounded-memory";
  headers: RawAxiosResponseHeaders;
}

export class DownloadDeliveryError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "DownloadDeliveryError";
    this.code = code;
  }
}

/**
 * Deliver an authenticated response without materializing the entire payload
 * in browser memory. Chromium's File System Access API is the primary path and
 * applies disk backpressure one response chunk at a time. Browsers without a
 * writable file sink receive an explicitly capped compatibility download.
 */
export async function downloadStreamedResponse({
  url,
  method = "GET",
  params,
  data,
  suggestedFilename,
  signal,
  maxFallbackBytes = MAX_BOUNDED_DOWNLOAD_FALLBACK_BYTES,
  validateHeaders,
}: StreamedDownloadRequest): Promise<StreamedDownloadResult> {
  if (!Number.isSafeInteger(maxFallbackBytes) || maxFallbackBytes <= 0) {
    throw new Error("The bounded download limit must be a positive integer");
  }

  const picker = typeof window === "undefined"
    ? undefined
    : (window as FilePickerWindow).showSaveFilePicker;
  // Request the handle while the click still owns transient user activation.
  // The file is not opened or truncated until the server has accepted the
  // authenticated export request.
  const fileHandle = picker
    ? await picker.call(window, { suggestedName: safeSuggestedFilename(suggestedFilename) })
    : null;

  const controller = new AbortController();
  const abortFromCaller = () => controller.abort(signal?.reason);
  if (signal?.aborted) abortFromCaller();
  else signal?.addEventListener("abort", abortFromCaller, { once: true });

  const abortForSessionReset = () => controller.abort("session-reset");
  let unsubscribeSessionResets: () => void = () => undefined;
  if (typeof window !== "undefined") {
    window.addEventListener(SENSITIVE_STATE_RESET_EVENT, abortForSessionReset);
    unsubscribeSessionResets = subscribeToSessionResets(abortForSessionReset);
  }
  const hardTimeout = globalThis.setTimeout(
    () => controller.abort("download-hard-timeout"),
    DOWNLOAD_HARD_TIMEOUT_MS,
  );

  let writable: FileDownloadWritable | null = null;
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  try {
    const response = await apiClient.request<ReadableStream<Uint8Array>>({
      url,
      method,
      params,
      data,
      adapter: "fetch",
      responseType: "stream",
      timeout: DOWNLOAD_HARD_TIMEOUT_MS,
      signal: controller.signal,
    });
    const stream = response.data;
    if (!stream || typeof stream.getReader !== "function") {
      throw new DownloadDeliveryError(
        "DOWNLOAD_STREAM_UNAVAILABLE",
        "This browser did not expose a safe response stream for the download.",
      );
    }

    const filename = attachmentFilename(
      response.headers["content-disposition"],
      suggestedFilename,
    );
    const contentLength = parseContentLength(response.headers["content-length"]);
    reader = stream.getReader();
    // Validate download identity/history before opening or truncating the
    // selected file and before retaining a compatibility Blob. If validation
    // fails, the catch path cancels the unread response stream.
    validateHeaders?.(response.headers);

    if (fileHandle) {
      writable = await fileHandle.createWritable();
      const bytesWritten = await copyStreamToWritable(
        reader,
        writable,
        controller,
      );
      await writable.close();
      writable = null;
      reader = null;
      return {
        filename,
        bytesWritten,
        delivery: "file-system",
        headers: response.headers,
      };
    }

    if (contentLength !== null && contentLength > maxFallbackBytes) {
      await reader.cancel("bounded-download-limit");
      reader = null;
      throw unsupportedLargeDownloadError(maxFallbackBytes);
    }
    const { parts, bytesWritten } = await readBoundedStream(
      reader,
      maxFallbackBytes,
      controller,
    );
    reader = null;
    triggerBlobDownload(
      new Blob(parts, {
        type: String(response.headers["content-type"] ?? "application/octet-stream"),
      }),
      filename,
    );
    return {
      filename,
      bytesWritten,
      delivery: "bounded-memory",
      headers: response.headers,
    };
  } catch (error) {
    if (writable?.abort) await writable.abort(error).catch(() => undefined);
    if (reader) await reader.cancel(error).catch(() => undefined);
    if (controller.signal.aborted && controller.signal.reason === "download-hard-timeout") {
      throw new DownloadDeliveryError(
        "DOWNLOAD_TIMEOUT",
        "The export did not finish within 10 minutes. No partial browser copy was kept.",
      );
    }
    throw error;
  } finally {
    globalThis.clearTimeout(hardTimeout);
    signal?.removeEventListener("abort", abortFromCaller);
    if (typeof window !== "undefined") {
      window.removeEventListener(SENSITIVE_STATE_RESET_EVENT, abortForSessionReset);
    }
    unsubscribeSessionResets();
  }
}

async function copyStreamToWritable(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  writable: FileDownloadWritable,
  controller: AbortController,
) {
  let bytesWritten = 0;
  while (true) {
    const result = await readWithIdleTimeout(reader, controller);
    if (result.done) return bytesWritten;
    await writable.write(result.value);
    bytesWritten += result.value.byteLength;
  }
}

async function readBoundedStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  maxBytes: number,
  controller: AbortController,
) {
  const parts: ArrayBuffer[] = [];
  let bytesWritten = 0;
  while (true) {
    const result = await readWithIdleTimeout(reader, controller);
    if (result.done) return { parts, bytesWritten };
    bytesWritten += result.value.byteLength;
    if (bytesWritten > maxBytes) {
      await reader.cancel("bounded-download-limit");
      throw unsupportedLargeDownloadError(maxBytes);
    }
    // Copy exactly one network chunk so the retained fallback envelope is
    // independent of an implementation's pooled backing ArrayBuffer.
    const part = new Uint8Array(result.value.byteLength);
    part.set(result.value);
    parts.push(part.buffer);
  }
}

async function readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  controller: AbortController,
) {
  let timeout: ReturnType<typeof globalThis.setTimeout> | undefined;
  try {
    return await Promise.race([
      reader.read(),
      new Promise<never>((_resolve, reject) => {
        timeout = globalThis.setTimeout(() => {
          controller.abort("download-idle-timeout");
          reject(new DownloadDeliveryError(
            "DOWNLOAD_IDLE_TIMEOUT",
            "The export stopped transferring for 60 seconds. The partial file was discarded.",
          ));
        }, DOWNLOAD_IDLE_TIMEOUT_MS);
      }),
    ]);
  } finally {
    if (timeout !== undefined) globalThis.clearTimeout(timeout);
  }
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const objectUrl = window.URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    window.URL.revokeObjectURL(objectUrl);
  }
}

function unsupportedLargeDownloadError(maxBytes: number) {
  return new DownloadDeliveryError(
    "DOWNLOAD_BROWSER_LIMIT",
    `This browser cannot stream this large export directly to disk. `
      + `Its compatibility path is capped at ${Math.floor(maxBytes / (1024 * 1024))} MB. `
      + "Use the current Chrome or Edge release and try again.",
  );
}

function parseContentLength(value: unknown) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
}

export function attachmentFilename(value: unknown, fallback: string) {
  if (typeof value !== "string") return safeSuggestedFilename(fallback);
  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  const quotedMatch = value.match(/filename="([^"]+)"/i);
  const plainMatch = value.match(/filename=([^;]+)/i);
  const raw = utf8Match?.[1] ?? quotedMatch?.[1] ?? plainMatch?.[1];
  if (!raw) return safeSuggestedFilename(fallback);
  try {
    return safeSuggestedFilename(decodeURIComponent(raw.trim()));
  } catch {
    return safeSuggestedFilename(fallback);
  }
}

function safeSuggestedFilename(value: string) {
  return value.trim().replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, "_") || "download";
}
