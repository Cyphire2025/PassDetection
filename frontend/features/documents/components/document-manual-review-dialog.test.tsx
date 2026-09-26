import { StrictMode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DOCUMENT_DISTRIBUTION_LANES } from "../config/document-distribution-lanes";
import { DocumentManualReviewDialog } from "./document-manual-review-dialog";

afterEach(() => vi.unstubAllGlobals());
beforeEach(() => vi.stubGlobal("URL", class extends URL {
  static createObjectURL = vi.fn(() => "blob:review");
  static revokeObjectURL = vi.fn();
}));

it("replaces and revokes PDF preview URLs on file changes, strict remount and close", () => {
  let sequence = 0;
  const create = vi.fn(() => `blob:preview-${++sequence}`);
  const revoke = vi.fn();
  vi.stubGlobal("URL", class extends URL {
    static createObjectURL = create;
    static revokeObjectURL = revoke;
  });
  const dialog = (file: File) => (
    <StrictMode>
      <DocumentManualReviewDialog
        items={[{ fileIndex: 0, file, reason: "Review required" }]}
        lane={DOCUMENT_DISTRIBUTION_LANES.visa} pending={false} error={null}
        onClose={vi.fn()} onApprove={vi.fn()}
      />
    </StrictMode>
  );
  const { rerender, unmount } = render(dialog(new File(["first"], "first.pdf")));
  const first = screen.getByRole("link", { name: "Preview first.pdf in a new tab" }).getAttribute("href");
  expect(first).toMatch(/^blob:preview-/);
  rerender(dialog(new File(["second"], "second.pdf")));
  const second = screen.getByRole("link", { name: "Preview second.pdf in a new tab" }).getAttribute("href");
  expect(second).not.toBe(first);
  expect(revoke).toHaveBeenCalledWith(first);
  unmount();
  expect(revoke).toHaveBeenCalledWith(second);
  expect(revoke.mock.calls.map(([url]) => url).sort()).toEqual(
    create.mock.results.map(({ value }) => value).sort(),
  );
});

it("requires explicit consent, blocks close and approval while pending and shows server errors", () => {
  const onClose = vi.fn();
  const onApprove = vi.fn();
  const props = {
    items: [{ fileIndex: 0, file: new File(["pdf"], "review.pdf"), reason: "Low confidence" }],
    lane: DOCUMENT_DISTRIBUTION_LANES.visa, pending: false, error: null, onClose, onApprove,
  };
  const { rerender } = render(<DocumentManualReviewDialog {...props} />);
  const approve = screen.getByRole("button", { name: /Approve & upload/ });
  expect(approve).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(approve).toBeEnabled();
  fireEvent.click(approve);
  expect(onApprove).toHaveBeenCalledOnce();
  rerender(<DocumentManualReviewDialog {...props} pending />);
  expect(approve).toBeDisabled();
  expect(screen.getByRole("checkbox")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  expect(onClose).not.toHaveBeenCalled();
  rerender(<DocumentManualReviewDialog {...props} error="Approval expired; review again." />);
  expect(screen.getByRole("alert")).toHaveTextContent("Approval expired; review again.");
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalledOnce();
});

it.each([
  { phase: "approving" as const, pending: true, total: 4, completed: 2, uploaded: 0, rejected: 1, expected: 50, status: "Checking selected approvals" },
  { phase: "approving" as const, pending: false, total: 0, completed: 0, uploaded: 0, rejected: 0, expected: 0, status: "Selected approval progress" },
  { phase: "uploading" as const, pending: true, total: 4, completed: 4, uploaded: 1, rejected: 2, expected: 50, status: "Uploading selected PDFs" },
  { phase: "uploading" as const, pending: false, total: 4, completed: 4, uploaded: 5, rejected: 2, expected: 100, status: "Selected upload progress" },
])("reports $phase progress accurately (pending=$pending, total=$total)", ({ pending, expected, status, ...progress }) => {
  render(<DocumentManualReviewDialog items={[]} lane={DOCUMENT_DISTRIBUTION_LANES.visa}
    pending={pending} error={null} progress={progress} onClose={vi.fn()} onApprove={vi.fn()} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", String(expected));
  expect(screen.getByRole("status")).toHaveTextContent(status);
  expect(screen.getByRole("checkbox")).toBeDisabled();
  expect(screen.getByRole("button", { name: /Approve & upload/ })).toBeDisabled();
  if (progress.rejected) expect(screen.getByText(/could not be accepted/)).toBeVisible();
});
