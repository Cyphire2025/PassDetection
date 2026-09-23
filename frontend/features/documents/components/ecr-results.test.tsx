import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { EcrBatch } from "@/types/ecr-checker.types";
import { EcrResults, ecrItemDisplay } from "./ecr-results";

const batch: EcrBatch = {
  batch_id: "batch", title: "Passport checks", status: "completed_with_errors", expected_count: 1000,
  total_count: 1000, processed_count: 1000, ecr_count: 1, na_count: 997, review_count: 1, failed_count: 1,
  created_at: "2026-09-24T00:00:00Z",
  items: Array.from({ length: 1000 }, (_, index) => ({
    id: String(index), client_id: String(index), original_filename: index < 2 ? "duplicate.jpg" : `passport-${index}.jpg`,
    status: index === 3 ? "failed" : "completed",
    result: index === 0 ? "ECR" : index === 2 ? "NEEDS_REVIEW" : index === 3 ? null : "NA",
    reason: index === 2 ? "Top edge is cropped" : null,
  })),
};

describe("ECR result review", () => {
  it("never renders failed, pending or unclassified items as NA", () => {
    expect(ecrItemDisplay({ status: "failed", result: "NA" }).label).toBe("Failed");
    expect(ecrItemDisplay({ status: "queued", result: null }).label).toBe("Queued");
    expect(ecrItemDisplay({ status: "completed", result: null }).label).toBe("Needs review");
    expect(ecrItemDisplay({ status: "completed", result: "ECR" }).className).toContain("text-red-600");
    expect(ecrItemDisplay({ status: "completed", result: "NA" }).className).toBe("text-black");
  });

  it("paginates 1000 rows, keeps duplicates, and filters review details", () => {
    render(<EcrResults batch={batch} action={null} onAction={vi.fn()} />);
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(51);
    expect(screen.getAllByText("duplicate.jpg")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Page 2 of 20")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Needs review (1)" }));
    expect(screen.getByText("Top edge is cropped")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Download Excel" })).toBeEnabled();
  });

  it("prevents downloading an incomplete analysis", () => {
    render(<EcrResults batch={{ ...batch, status: "processing", processed_count: 12 }} action={null} onAction={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Download Excel" })).toBeDisabled();
    expect(screen.getByRole("progressbar", { name: "ECR checking progress" })).toHaveAttribute("aria-valuenow", "1");
    expect(screen.queryByRole("button", { name: "Retry failed checks" })).not.toBeInTheDocument();
  });
});
