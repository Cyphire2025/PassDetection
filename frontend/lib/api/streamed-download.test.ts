import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./client", () => ({
  default: {
    request: vi.fn(),
  },
}));

import apiClient from "./client";
import { dispatchSensitiveStateReset } from "@/features/auth/services/session-state";
import {
  attachmentFilename,
  downloadStreamedResponse,
} from "./streamed-download";

const requestMock = vi.mocked(apiClient.request);

function byteStream(...chunks: number[][]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(Uint8Array.from(chunk)));
      controller.close();
    },
  });
}

describe("downloadStreamedResponse", () => {
  beforeEach(() => {
    requestMock.mockReset();
    Reflect.deleteProperty(window, "showSaveFilePicker");
    Object.defineProperty(window.URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:bounded-download"),
    });
    Object.defineProperty(window.URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    vi.spyOn(window, "prompt").mockReset().mockImplementation((_message, suggestedName) => suggestedName ?? "download.xlsx");
  });

  it("writes one response chunk at a time to a browser file sink", async () => {
    const writtenChunks: number[][] = [];
    const write = vi.fn(async (chunk: Uint8Array) => {
      writtenChunks.push(Array.from(chunk));
    });
    const close = vi.fn(async () => undefined);
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: vi.fn(async () => ({
        createWritable: async () => ({ write, close }),
      })),
    });
    requestMock.mockResolvedValueOnce({
      data: byteStream([1, 2], [3, 4, 5]),
      headers: {
        "content-disposition": 'attachment; filename="server-export.zip"',
        "content-type": "application/zip",
        "content-length": "5",
      },
    } as never);

    const result = await downloadStreamedResponse({
      url: "/api/export",
      suggestedFilename: "expected.zip",
    });

    expect(requestMock).toHaveBeenCalledWith(expect.objectContaining({
      adapter: "fetch",
      responseType: "stream",
    }));
    expect(write).toHaveBeenCalledTimes(2);
    expect(writtenChunks).toEqual([[1, 2], [3, 4, 5]]);
    expect(close).toHaveBeenCalledOnce();
    expect(result).toMatchObject({
      bytesWritten: 5,
      delivery: "file-system",
      filename: "server-export.zip",
    });
    expect(window.URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("uses an explicitly capped compatibility Blob when no writable sink exists", async () => {
    requestMock.mockResolvedValueOnce({
      data: byteStream([1, 2], [3]),
      headers: {
        "content-disposition": 'attachment; filename="bounded.xlsx"',
        "content-type": "application/octet-stream",
        "content-length": "3",
      },
    } as never);

    const result = await downloadStreamedResponse({
      url: "/api/export",
      suggestedFilename: "expected.xlsx",
      maxFallbackBytes: 3,
    });

    expect(result.delivery).toBe("bounded-memory");
    expect(result.bytesWritten).toBe(3);
    expect(window.URL.createObjectURL).toHaveBeenCalledOnce();
    expect(window.URL.revokeObjectURL).toHaveBeenCalledWith("blob:bounded-download");
  });

  it("rejects an oversized compatibility response before retaining its body", async () => {
    const cancel = vi.fn(async () => undefined);
    requestMock.mockResolvedValueOnce({
      data: { getReader: () => ({ cancel, read: vi.fn() }) },
      headers: {
        "content-type": "application/zip",
        "content-length": "4",
      },
    } as never);

    await expect(downloadStreamedResponse({
      url: "/api/export",
      suggestedFilename: "large.zip",
      maxFallbackBytes: 3,
    })).rejects.toMatchObject({
      code: "DOWNLOAD_BROWSER_LIMIT",
    });
    expect(cancel).toHaveBeenCalledOnce();
    expect(window.URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("validates response identity before opening a file sink or retaining bytes", async () => {
    const cancel = vi.fn(async () => undefined);
    const createWritable = vi.fn(async () => ({
      write: vi.fn(async () => undefined),
      close: vi.fn(async () => undefined),
    }));
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: vi.fn(async () => ({ createWritable })),
    });
    requestMock.mockResolvedValueOnce({
      data: { getReader: () => ({ cancel, read: vi.fn() }) },
      headers: { "content-type": "application/zip" },
    } as never);

    await expect(downloadStreamedResponse({
      url: "/api/export",
      suggestedFilename: "export.zip",
      validateHeaders: () => {
        throw new Error("missing prepared-download identity");
      },
    })).rejects.toThrow("missing prepared-download identity");

    expect(cancel).toHaveBeenCalledOnce();
    expect(createWritable).not.toHaveBeenCalled();
    expect(window.URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("opens Save As before requesting Excel and honors the user's name over server headers", async () => {
    const write = vi.fn(async () => undefined);
    const picker = vi.fn(async () => ({
      name: "My renamed trip.xlsx",
      createWritable: async () => ({ write, close: vi.fn(async () => undefined) }),
    }));
    Object.defineProperty(window, "showSaveFilePicker", { configurable: true, value: picker });
    requestMock.mockResolvedValue({
      data: byteStream([1, 2, 3]),
      headers: { "content-disposition": 'attachment; filename="fixed-server-name.xlsx"' },
    } as never);

    const pending = downloadStreamedResponse({ url: "/excel", suggestedFilename: "Trip.xlsx" });
    expect(picker).toHaveBeenCalledOnce();
    expect(requestMock).not.toHaveBeenCalled();
    const result = await pending;
    expect(picker).toHaveBeenCalledWith(expect.objectContaining({
      suggestedName: expect.stringMatching(/^Trip-\d{4}-\d{2}-\d{2}_.*-\d{4,}\.xlsx$/),
      types: [{ description: "Excel workbook", accept: {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      } }],
    }));
    expect(result.filename).toBe("My renamed trip.xlsx");
    expect(write).toHaveBeenCalledOnce();
    expect(window.prompt).not.toHaveBeenCalled();
  });

  it("does not request or silently download an export when Save As is cancelled", async () => {
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: vi.fn().mockRejectedValue(new DOMException("Cancelled", "AbortError")),
    });
    await expect(downloadStreamedResponse({ url: "/excel", suggestedFilename: "Trip.xlsx" }))
      .rejects.toMatchObject({ name: "AbortError" });
    expect(requestMock).not.toHaveBeenCalled();
    expect(window.prompt).not.toHaveBeenCalled();
    expect(window.URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("does not export under a changed session after the user chooses a file", async () => {
    let selectFile!: (value: { createWritable: ReturnType<typeof vi.fn> }) => void;
    const createWritable = vi.fn();
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: () => new Promise((resolve) => { selectFile = resolve; }),
    });
    const pending = downloadStreamedResponse({ url: "/excel", suggestedFilename: "Trip.xlsx" });
    dispatchSensitiveStateReset("account_changed");
    selectFile({ createWritable });
    await expect(pending).rejects.toBe("session-reset");
    expect(requestMock).not.toHaveBeenCalled();
    expect(createWritable).not.toHaveBeenCalled();
  });

  it("uses the compatibility rename choice even when the server provides a fixed name", async () => {
    vi.mocked(window.prompt).mockReturnValueOnce("Office roster");
    requestMock.mockResolvedValueOnce({
      data: byteStream([1]),
      headers: { "content-disposition": 'attachment; filename="fixed.xlsx"' },
    } as never);
    let downloadedName = "";
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      downloadedName = this.download;
    });
    const result = await downloadStreamedResponse({ url: "/excel", suggestedFilename: "Trip.xlsx" });
    expect(result.filename).toBe("Office roster.xlsx");
    expect(downloadedName).toBe("Office roster.xlsx");
  });

  it("discards the partial file if the session changes during the final write", async () => {
    const close = vi.fn(async () => undefined);
    const abort = vi.fn(async () => undefined);
    Object.defineProperty(window, "showSaveFilePicker", {
      configurable: true,
      value: async () => ({
        createWritable: async () => ({
          write: async () => { dispatchSensitiveStateReset("logout"); },
          close,
          abort,
        }),
      }),
    });
    requestMock.mockResolvedValueOnce({ data: byteStream([1]), headers: {} } as never);
    await expect(downloadStreamedResponse({ url: "/excel", suggestedFilename: "Trip.xlsx" }))
      .rejects.toBe("session-reset");
    expect(close).not.toHaveBeenCalled();
    expect(abort).toHaveBeenCalledOnce();
  });

  it("cancels the compatibility rename prompt without making a request", async () => {
    vi.mocked(window.prompt).mockReturnValueOnce(null);
    await expect(downloadStreamedResponse({ url: "/excel", suggestedFilename: "Trip.xlsx" }))
      .rejects.toMatchObject({ name: "AbortError" });
    expect(requestMock).not.toHaveBeenCalled();
  });
});

describe("attachmentFilename", () => {
  it("decodes UTF-8 names and removes filesystem separators", () => {
    expect(attachmentFilename(
      "attachment; filename*=UTF-8''Trip%20A%2FPassports.zip",
      "fallback.zip",
    )).toBe("Trip A_Passports.zip");
  });
});
