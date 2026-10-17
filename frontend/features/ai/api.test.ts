import { describe, expect, it, vi } from "vitest";
import { assistantMessage, decodeAssistantStream } from "./api";

vi.mock("@/lib/api/client", () => ({ default: {} }));

function bytes(chunks: string[]) {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({ start(controller) { chunks.forEach((part) => controller.enqueue(encoder.encode(part))); controller.close(); } });
}

describe("assistant streaming boundary", () => {
  it("preserves streamed text, CRLF chunk boundaries and comments until a saved completion", async () => {
    const body = bytes([': keep-alive\r', '\n\r\n', 'event: assistant\r\ndata: {"type":"text_delta","text":"Jour', 'ney"}\r', '\n\r', '\nevent: assistant\r\ndata: {"type":"done","request_id":"test"}\r\n\r\n']);
    const result = [];
    for await (const event of decodeAssistantStream(body, new AbortController().signal)) result.push(event);
    expect(result).toEqual([{ type: "text_delta", text: "Journey" }, { type: "done", request_id: "test" }]);
  });

  it("does not mistake a partial answer for a saved response", async () => {
    const consume = async () => { for await (const event of decodeAssistantStream(bytes(['data: {"type":"text_delta","text":"Partial"}\n\n']), new AbortController().signal)) void event; };
    await expect(consume()).rejects.toThrow("before the answer was saved");
  });

  it("accepts a bounded, actionable server error as the terminal event", async () => {
    const results = [];
    for await (const event of decodeAssistantStream(bytes(['data: {"type":"error","message":"Daily limit reached","code":"daily_limit"}\n\n']), new AbortController().signal)) results.push(event);
    expect(results).toHaveLength(1);
    expect(assistantMessage({ code: "file_rejected", message: "File checks are temporarily unavailable" }, "Fallback")).toBe("File checks are temporarily unavailable");
  });

  it("caps an unterminated frame", async () => {
    const consume = async () => { for await (const event of decodeAssistantStream(bytes(['x'.repeat(262145)]), new AbortController().signal)) void event; };
    await expect(consume()).rejects.toThrow("safe size limit");
  });
});
