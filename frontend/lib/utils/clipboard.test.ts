import { afterEach, describe, expect, it, vi } from "vitest";
import { copyTextToClipboard } from "./clipboard";

const originalCommand = Object.getOwnPropertyDescriptor(document, "execCommand");
afterEach(() => {
  vi.unstubAllGlobals();
  if (originalCommand) Object.defineProperty(document, "execCommand", originalCommand);
  else Reflect.deleteProperty(document, "execCommand");
});

function mockCommand(command: () => boolean) {
  Object.defineProperty(document, "execCommand", { configurable: true, value: command });
}

describe("clipboard fallback resource cleanup", () => {
  it("removes copied sensitive text from the DOM if the browser throws", async () => {
    vi.stubGlobal("navigator", {});
    const command = vi.fn(() => { throw new DOMException("Clipboard denied", "SecurityError"); });
    mockCommand(command);
    await expect(copyTextToClipboard("private-upload-link-token")).rejects.toThrow("Clipboard denied");
    expect(document.body.querySelector("textarea")).toBeNull();
  });

  it("cleans up when the copy command returns false", async () => {
    vi.stubGlobal("navigator", {});
    mockCommand(vi.fn(() => false));
    await expect(copyTextToClipboard("private-upload-link-token")).rejects.toThrow("Copy command was rejected");
    expect(document.body.querySelector("textarea")).toBeNull();
  });
});

