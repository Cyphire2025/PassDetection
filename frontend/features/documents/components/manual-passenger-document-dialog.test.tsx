import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DocumentPassengerReviewRow, DistributedDocument } from "@/types/document-distribution.types";
import { ManualPassengerDocumentDialog } from "./manual-passenger-document-dialog";
import { DocumentRowActionMenu } from "./document-workspace-review";
import { DocumentWorkspaceReviewRows } from "./document-workspace-review-rows";

const document = { id: "saved-1", original_filename: "shared.pdf", updated_at: "2026-10-16T00:00:00Z" } as DistributedDocument;
const row: DocumentPassengerReviewRow = { passenger_id: "person-1", passenger_name: "Same Name", passport_number: "P1234", departure_city: null, document: null, documents: [] };

describe("manual passenger document assignment", () => {
  it("uploads directly to the shown passenger without a classification approval step", () => {
    const upload = vi.fn();
    render(<ManualPassengerDocumentDialog row={row} mode="add" pending={false} error={null} onClose={vi.fn()} onUpload={upload} />);
    expect(screen.getByText("Passport: P1234")).toBeInTheDocument();
    const file = new File(["pdf"], "my-document.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Choose PDF"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload and save" }));
    expect(upload).toHaveBeenCalledWith(file, []);
  });

  it("replaces exactly the selected saved document with its current version", () => {
    const upload = vi.fn();
    render(<ManualPassengerDocumentDialog row={{ ...row, documents: [document, { ...document, id: "saved-2", original_filename: "second.pdf" }] }} mode="replace" pending={false} error={null} onClose={vi.fn()} onUpload={upload} />);
    fireEvent.change(screen.getByLabelText("Document to replace"), { target: { value: "saved-2" } });
    const file = new File(["pdf"], "new.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("Choose PDF"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Replace and save" }));
    expect(upload).toHaveBeenCalledWith(file, [{ id: "saved-2", updated_at: document.updated_at }]);
    expect(screen.getByText(/Other passengers who share it keep their assignment/)).toBeInTheDocument();
  });

  it("offers Upload for missing PDFs and Replace plus Add another for existing PDFs", () => {
    const manual = vi.fn();
    const props = { row, documentType: "visa" as const, pending: false, onReupload: vi.fn(), onManualUpload: manual, onRemoveAssignment: vi.fn() };
    const { rerender } = render(<DocumentRowActionMenu {...props} documents={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Same Name document actions" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Upload document" }));
    expect(manual).toHaveBeenCalledWith(row, "add");
    rerender(<DocumentRowActionMenu {...props} documents={[document]} />);
    fireEvent.click(screen.getByRole("button", { name: "Same Name document actions" }));
    expect(screen.getByRole("menuitem", { name: "Add another document" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("menuitem", { name: "Replace document" }));
    expect(manual).toHaveBeenCalledWith(row, "replace");
  });

  it("keeps the row checkbox controlled when an empty row receives its saved PDF", () => {
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      const props = { rows: [row], pdfCountsByPassengerId: new Map(), activeSelectedAssignedDocumentIdSet: new Set<string>(), documentType: "visa" as const, showRowActions: true, removalPending: false, reuploadPending: false, searchQuery: "", onToggleRowDocuments: vi.fn(), onReupload: vi.fn(), onRemoveAssignment: vi.fn(), onResend: vi.fn() };
      const { rerender } = render(<table><DocumentWorkspaceReviewRows {...props} documentsByPassengerId={new Map([[row.passenger_id, []]])} /></table>);
      expect(screen.getByRole("checkbox")).not.toBeChecked();
      rerender(<table><DocumentWorkspaceReviewRows {...props} documentsByPassengerId={new Map([[row.passenger_id, [{ ...document, match_confidence: 1, match_status: "matched", delivery_status: "not_sent" }]]])} /></table>);
      expect(screen.getByRole("checkbox")).not.toBeChecked();
      expect(errors).not.toHaveBeenCalled();
    } finally { errors.mockRestore(); }
  });
});
