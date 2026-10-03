import { afterEach, expect, it, vi } from "vitest";
import { saveTransferFile } from "./save-transfer-file";

afterEach(() => { delete (window as Window & { showSaveFilePicker?: unknown }).showSaveFilePicker; vi.restoreAllMocks(); });
it("reports an actual save only after the selected file writer finishes and closes", async () => {
  let close!: () => void;
  const write = vi.fn().mockResolvedValue(undefined);
  const closed = new Promise<void>((resolve) => { close = resolve; });
  Object.defineProperty(window, "showSaveFilePicker", { configurable: true, value: vi.fn().mockResolvedValue({ createWritable: async () => ({ write, close: () => closed }) }) });
  const complete = vi.fn();
  const result = saveTransferFile(new Blob(["bytes"]), "report.pdf", "application/pdf").then(complete);
  await vi.waitFor(() => expect(write).toHaveBeenCalledOnce());
  expect(complete).not.toHaveBeenCalled(); close(); await result;
  expect(complete).toHaveBeenCalledWith("saved");
});
it("does not report saved when the file picker is cancelled", async () => {
  Object.defineProperty(window, "showSaveFilePicker", { configurable: true, value: vi.fn().mockRejectedValue(new DOMException("Cancelled", "AbortError")) });
  await expect(saveTransferFile(new Blob(["bytes"]), "report.pdf", "application/pdf")).rejects.toMatchObject({ name: "AbortError" });
});
