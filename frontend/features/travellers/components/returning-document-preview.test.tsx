import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { returningApi } from "../api/returning.api";
import { ReturningDocumentPreview } from "./returning-document-preview";

vi.mock("../api/returning.api", () => ({ returningApi: { document: vi.fn() } }));
const document = { id: "synthetic-asset", label: "Passport document", content_type: "application/pdf", available: true };
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private-pdf"), revokeObjectURL: vi.fn() }));
});

describe("protected document display boundary", () => {
  it("requires explicit PDF visibility acknowledgement because iframe load can also mean blocked content", async () => {
    vi.mocked(returningApi.document).mockResolvedValue(new Blob(["synthetic PDF"], { type: "application/pdf" }));
    const viewed = vi.fn();
    const view = render(<ReturningDocumentPreview document={document} onViewed={viewed} onClose={vi.fn()} />);
    fireEvent.load(await screen.findByTitle("Passport document"));
    expect(viewed).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "I can see and have reviewed this PDF" }));
    expect(viewed).toHaveBeenCalledWith("synthetic-asset");
    view.unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:private-pdf");
  });

  it("shows the safe normalized API failure without creating a document URL", async () => {
    vi.mocked(returningApi.document).mockRejectedValue({ code: "claim_expired", status: 410, message: "Your secure session expired. Start again or submit fresh documents." });
    render(<ReturningDocumentPreview document={document} onViewed={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Your secure session expired");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it("aborts a closed preview and ignores a late protected response", async () => {
    let finish!: (blob: Blob) => void;
    vi.mocked(returningApi.document).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const viewed = vi.fn();
    const view = render(<ReturningDocumentPreview document={document} onViewed={viewed} onClose={vi.fn()} />);
    await waitFor(() => expect(returningApi.document).toHaveBeenCalledOnce());
    const signal = vi.mocked(returningApi.document).mock.calls[0][1]!;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => finish(new Blob(["late"], { type: "application/pdf" })));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(viewed).not.toHaveBeenCalled();
  });
});
