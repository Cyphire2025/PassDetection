import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { DocumentVerificationResult, VerifiedDistributedDocument } from "@/types/document-distribution.types";
import { DocumentSentStatus, VerificationPanel } from "./document-workspace-review";

const file = (filename: string, overrides: Partial<VerifiedDistributedDocument> = {}): VerifiedDistributedDocument => ({
  filename, detected_type: "unknown", accepted: false, reason: "Review the original PDF",
  matched_passenger_id: null, matched_passenger_name: null, matched_passenger_ids: [], matched_passenger_names: [],
  match_confidence: 0, match_status: "needs_review", match_reason: null, staging_receipt: null,
  manual_review_available: true, ...overrides,
});
const verification: DocumentVerificationResult = {
  group_id: "synthetic-group", document_type: "visa", total_count: 6, accepted_count: 1, rejected_count: 5,
  files: [
    file("accepted.pdf", { accepted: true, detected_type: "visa", manual_review_available: false,
      matched_passenger_names: ["One", "Two", "Three", "Four", "Five", "Six"] }),
    file("unknown-first.pdf"), file("unknown-second.pdf"), file("known-type.pdf", { detected_type: "visa" }),
    file("approved-type.pdf", { manual_type_approved: true }), file("missing-original.pdf"),
  ],
};
function props() {
  return { verification, reviewableFileIndexes: new Set([1, 2, 3, 4]), selectedReviewFileIndexes: new Set([1, 3, 4]),
    onToggleReviewFile: vi.fn(), onSelectAllReviewFiles: vi.fn(), onReviewSelected: vi.fn() };
}

it("counts and selects only original-backed unknown files that still require type approval", () => {
  const actions = props();
  const view = render(<VerificationPanel {...actions} />);
  const all = screen.getByRole("checkbox", { name: "Select all eligible" });
  expect(all).toHaveAttribute("aria-checked", "mixed");
  expect((all as HTMLInputElement).indeterminate).toBe(true);
  expect(screen.getAllByRole("checkbox")).toHaveLength(3);
  expect(screen.getByText("1 of 2 selected")).toBeVisible();
  fireEvent.click(all);
  expect(actions.onSelectAllReviewFiles).toHaveBeenCalledExactlyOnceWith(true);
  fireEvent.click(screen.getByRole("checkbox", { name: "Select file 3: unknown-second.pdf for review" }));
  expect(actions.onToggleReviewFile).toHaveBeenCalledExactlyOnceWith(2, true);
  fireEvent.click(screen.getByRole("button", { name: "Approve & upload selected (1)" }));
  expect(actions.onReviewSelected).toHaveBeenCalledOnce();
  view.rerender(<VerificationPanel {...actions} selectedReviewFileIndexes={new Set([1, 2])} />);
  expect(all).toBeChecked();
  expect((all as HTMLInputElement).indeterminate).toBe(false);
  expect(screen.getByText(/Type approved; a confirmed passenger match is still needed/)).toBeVisible();
  expect(screen.getByText(/Matched 6 passengers: One, Two, Three, Four, \+2 more/)).toBeVisible();
});

it.each(["manualReviewDisabled", "manualReviewLocked"] as const)("keeps all approval controls inactive while %s", flag => {
  const actions = props();
  render(<VerificationPanel {...actions} {...{ [flag]: true }} />);
  for (const checkbox of screen.getAllByRole("checkbox")) expect(checkbox).toBeDisabled();
  const approve = screen.getByRole("button", { name: "Approve & upload selected (1)" });
  expect(approve).toBeDisabled();
  fireEvent.click(approve);
  expect(actions.onReviewSelected).not.toHaveBeenCalled();
  if (flag === "manualReviewLocked") expect(screen.getByText(/Finish or discard it before approving/)).toBeVisible();
});

it("requires the original file for individual review and does not offer uploaded PDFs again", () => {
  const review = vi.fn();
  const view = render(<VerificationPanel verification={verification} reviewableFileIndexes={new Set([1])} onReviewFile={review} />);
  fireEvent.click(screen.getByRole("button", { name: "Review and approve unknown-first.pdf" }));
  expect(review).toHaveBeenCalledExactlyOnceWith(1);
  expect(screen.getByRole("button", { name: "Review and approve missing-original.pdf" })).toBeDisabled();
  view.rerender(<VerificationPanel verification={{ ...verification, rejected_count: 0, files: [
    file("already-uploaded.pdf", { accepted: true, manual_uploaded: true }),
  ] }} />);
  expect(screen.getByRole("status")).toHaveTextContent("1 PDF uploaded · 1 manually approved");
  expect(screen.getByText("No accepted PDFs are waiting to be uploaded.")).toBeVisible();
  expect(screen.queryByText("already-uploaded.pdf")).not.toBeInTheDocument();
});

it.each([
  ["queued", "In progress"], ["processing", "In progress"], ["delivery_unknown", "Outcome unknown"],
  ["failed", "Failed"], ["not_sent", "Not sent"],
])("does not invent sent status or a resend action for %s", (status, label) => {
  const resend = vi.fn();
  render(<DocumentSentStatus status={status} sentTo={null} sentAt={null} canResend onResend={resend} />);
  expect(screen.getByText(label)).toBeVisible();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(resend).not.toHaveBeenCalled();
});

it("resends a confirmed send only through its explicit available action", () => {
  const resend = vi.fn();
  const view = render(<DocumentSentStatus status="sent" sentTo={null} sentAt={null} canResend={false} onResend={resend} />);
  expect(screen.getByText("WhatsApp accepted")).toBeVisible();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  view.rerender(<DocumentSentStatus status="sent" sentTo="Synthetic recipient" sentAt={null} canResend onResend={resend} />);
  expect(resend).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Resend explicitly" }));
  expect(resend).toHaveBeenCalledOnce();
});
