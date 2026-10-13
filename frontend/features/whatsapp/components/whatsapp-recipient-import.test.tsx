import { useState } from "react";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { whatsappApi } from "../api/whatsapp.api";
import type { RecipientImportPreview } from "../utils/recipient-import";
import type { ManualContact } from "./whatsapp-dialog-ui";
import { useRecipientExcelPreview } from "./whatsapp-recipient-import";

vi.mock("../api/whatsapp.api", () => ({ whatsappApi: { previewContacts: vi.fn() } }));
function largePreview(): RecipientImportPreview {
  return { recipient_count: 1, accepted_count: 1, recipients: [{ name: "Delivery contact", phone_number: "+919999999999" }], rejected_count: 699, rejected_counts: { duplicate_phone: 699 }, rejected_rows_truncated: true, omitted_rejected_count: 199, rejected_rows: Array.from({ length: 500 }, (_, index) => ({ sheet_name: "Travellers", row_number: index + 3, raw_name: `Traveller ${index + 2}`, raw_phone_number: "+919999999999", reason_code: "duplicate_phone", reason: "Shared number" })) };
}
function setup() {
  return renderHook(() => { const [contacts, setContacts] = useState<ManualContact[]>([]); return { contacts, setContacts, ...useRecipientExcelPreview({ contacts, setContacts, onStart: vi.fn() }) }; });
}
beforeEach(() => { vi.clearAllMocks(); vi.mocked(whatsappApi.previewContacts).mockResolvedValue(largePreview()); });
describe("retained original source for bounded Excel previews", () => {
  it("retains the 700-row source without expanding the 500-row preview or undoing recipient edits", async () => {
    const file = new File(["synthetic workbook"], "700-travellers.xlsx");
    const { result } = setup();
    await act(() => result.current.previewFile(file));
    expect(result.current.contacts).toHaveLength(1);
    expect(result.current.rejectedContacts).toHaveLength(500);
    expect(result.current.rejectedContactCount).toBe(699);
    expect(result.current.duplicateSourceFiles).toEqual([file]);
    act(() => result.current.setContacts([{ name: "Reviewed delivery contact", phone_number: "+918888888888" }]));
    expect(result.current.contacts[0].name).toBe("Reviewed delivery contact");
    expect(result.current.duplicateSourceFiles[0]).toBe(file);
    expect(result.current.importState).toMatchObject({ status: "success", retainedSourceFileCount: 1, omittedRejectedCount: 199 });
    act(() => result.current.resetImport());
    expect(result.current.duplicateSourceFiles).toEqual([]);
    expect(result.current.rejectedContactCount).toBe(0);
  });
  it("keeps multiple original workbooks and deduplicates the same selected file", async () => {
    const first = new File(["one"], "one.xlsx", { lastModified: 1 });
    const second = new File(["two"], "two.xlsx", { lastModified: 2 });
    const { result } = setup();
    await act(() => result.current.previewFile(first));
    await act(() => result.current.previewFile(first));
    await act(() => result.current.previewFile(second));
    expect(result.current.duplicateSourceFiles).toEqual([first, second]);
    expect(result.current.rejectedContacts).toHaveLength(1000);
  });
  it("rejects a truncated workbook with hidden invalid rows before merging any of it", async () => {
    const { result } = setup();
    vi.mocked(whatsappApi.previewContacts).mockResolvedValue({ ...largePreview(), rejected_counts: { duplicate_phone: 698, invalid_phone: 1 } });
    await act(() => result.current.previewFile(new File(["invalid"], "invalid.xlsx")));
    expect(result.current.importState).toMatchObject({ status: "error" });
    expect(result.current.contacts).toEqual([]);
    expect(result.current.rejectedContacts).toEqual([]);
    expect(result.current.duplicateSourceFiles).toEqual([]);
    act(() => result.current.dismissImportError());
    expect(result.current.importState.status).toBe("idle");
  });
  it("does not infer omitted-row safety when the authoritative counts are absent", async () => {
    vi.mocked(whatsappApi.previewContacts).mockResolvedValue({ ...largePreview(), rejected_counts: undefined });
    const { result } = setup();
    await act(() => result.current.previewFile(new File(["unknown"], "unknown.xlsx")));
    expect(result.current.importState.status).toBe("error");
    expect(result.current.duplicateSourceFiles).toEqual([]);
  });
  it("ignores a stale preview response and retains only the latest original file", async () => {
    let finish!: (preview: RecipientImportPreview) => void;
    vi.mocked(whatsappApi.previewContacts).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const { result } = setup();
    const older = new File(["old"], "old.xlsx"); const latest = new File(["new"], "new.xlsx");
    let oldRequest!: Promise<void>;
    act(() => { oldRequest = result.current.previewFile(older); });
    await act(() => result.current.previewFile(latest));
    await act(async () => { finish(largePreview()); await oldRequest; });
    expect(result.current.duplicateSourceFiles).toEqual([latest]);
    expect(vi.mocked(whatsappApi.previewContacts).mock.calls[0][1]?.aborted).toBe(true);
  });
  it("bounds retained source files before merging an eleventh workbook", async () => {
    const { result } = setup();
    for (let index = 0; index < 11; index++) await act(() => result.current.previewFile(new File([String(index)], `source-${index}.xlsx`)));
    expect(result.current.duplicateSourceFiles).toHaveLength(10);
    expect(result.current.importState).toMatchObject({ status: "error", message: expect.stringContaining("at most 10") });
  });
});
