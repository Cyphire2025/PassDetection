import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { expect, it, vi } from "vitest";
import { DocumentWorkspaceReviewControls } from "./document-workspace-review-controls";

it("offers the affected-passenger filter and exports its current view", () => {
  const props: ComponentProps<typeof DocumentWorkspaceReviewControls> = {
    assignedFileCount: 3,
    assignedPassengerCount: 2,
    needsAssignmentCount: 0,
    rejectedCount: 0,
    removalDocumentCount: 0,
    removalPassengerCount: 0,
    selectedAssignedDocumentCount: 0,
    selectedUnmatchedDocumentCount: 0,
    removalPending: false,
    removalConfirmationPending: false,
    deleteUnassignedPending: false,
    saveDisabled: false,
    savePending: false,
    saved: true,
    deliveryDisabled: false,
    exportPending: false,
    exportError: false,
    hasReviewData: true,
    physicalFileCount: 3,
    assignmentIssues: [],
    selectedDocumentIdSet: new Set(),
    reviewCounts: { all: 2, assigned: 2, missing: 0, sent: 0, not_sent: 2, multiple_pdfs: 1 },
    reviewFilter: "all",
    searchQuery: "",
    onRequestRemoval: vi.fn(),
    onDeleteUnassigned: vi.fn(),
    onSave: vi.fn(),
    onOpenDelivery: vi.fn(),
    onExport: vi.fn(),
    onToggleIssue: vi.fn(),
    onReviewFilterChange: vi.fn(),
    onClearSelectedAssignments: vi.fn(),
    onSearchQueryChange: vi.fn(),
  };
  const { rerender } = render(<DocumentWorkspaceReviewControls {...props} />);
  expect(screen.getByRole("button", { name: "All (2)" })).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByRole("button", { name: "Multiple PDFs (1)" }));
  expect(props.onReviewFilterChange).toHaveBeenCalledWith("multiple_pdfs");

  rerender(<DocumentWorkspaceReviewControls {...props} reviewFilter="multiple_pdfs" />);
  expect(screen.getByRole("button", { name: "Multiple PDFs (1)" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText(/Each shared PDF counts once per passenger/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Export Multiple PDFs Excel" }));
  expect(props.onExport).toHaveBeenCalledOnce();
  expect(props.onRequestRemoval).not.toHaveBeenCalled();
  expect(props.onOpenDelivery).not.toHaveBeenCalled();
});
