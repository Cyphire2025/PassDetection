import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { ReviewFieldsCard } from "./passport-review-card";
import type { ReviewFieldsCardProps } from "./passport-review-types";

const fields = { surname: "", given_names: "MAYA", passport_number: "SYNTHETIC123", nationality: "IND",
  date_of_birth: "1990-01-02", date_of_issue: "2020-03-04", date_of_expiry: "2030-03-04" };

function props(overrides: Partial<ReviewFieldsCardProps> = {}): ReviewFieldsCardProps {
  return {
    passport: { id: "synthetic-passport", status: "needs_review", extraction_revision: 4,
      created_at: "2026-01-01T12:00:00Z", updated_at: "2026-01-02T12:00:00Z" } as PassportSubmission,
    sourceFields: fields, conflicts: [], isSaving: false, canRetryAiVerification: true,
    isRetryingAiVerification: false, canReextract: true, isReextracting: false,
    reextractFeedback: null, approvalFeedback: null, formError: null,
    onFormError: vi.fn(), onConfirm: vi.fn().mockResolvedValue(undefined),
    onStaffApprove: vi.fn().mockResolvedValue({ outcome: "approved" }),
    onRetryAiVerification: vi.fn().mockResolvedValue(undefined), reviewerLabel: null, onReextract: vi.fn(),
    ...overrides,
  };
}

describe("passport field review", () => {
  it("prefills imported fields and sends reviewed values and a trimmed manual reason once", async () => {
    let finish: (() => void) | undefined;
    const onStaffApprove = vi.fn(() => new Promise((resolve) => { finish = () => resolve({ outcome: "approved" }); }));
    const value = props({ onStaffApprove: onStaffApprove as ReviewFieldsCardProps["onStaffApprove"] });
    render(<ReviewFieldsCard {...value} />);
    expect(screen.getByRole("textbox", { name: "Date Of Birth" })).toHaveValue("02/01/1990");
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "  MAYA JANE  " } });
    fireEvent.change(screen.getByRole("textbox", { name: /Review reason/ }), { target: { value: "  Compared with original  " } });
    const approve = screen.getByRole("button", { name: "Approve After Manual Review" });
    fireEvent.click(approve);
    fireEvent.click(approve);
    expect(onStaffApprove).toHaveBeenCalledTimes(1);
    expect(onStaffApprove).toHaveBeenCalledWith(expect.objectContaining({ given_names: "MAYA JANE", surname: "", date_of_birth: "1990-01-02" }), "Compared with original");
    expect(value.onConfirm).not.toHaveBeenCalled();
    await act(async () => finish?.());
  });

  it("rejects chronological date errors before any persistence action", () => {
    const value = props({ sourceFields: { ...fields, date_of_expiry: "2019-01-01" } });
    render(<ReviewFieldsCard {...value} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve After Manual Review" }));
    expect(value.onFormError).toHaveBeenCalledWith(expect.stringContaining("chronological"));
    expect(value.onStaffApprove).not.toHaveBeenCalled();
  });

  it("preserves manual values until an extracted conflict value is deliberately selected", () => {
    render(<ReviewFieldsCard {...props({ conflicts: [{ field: "passport_number", manual_value: "SYNTHETIC123", extracted_value: "SYNTHETIC456", status: "mismatch" }] })} />);
    const number = screen.getByRole("textbox", { name: "Passport Number" });
    expect(number).toHaveValue("SYNTHETIC123");
    fireEvent.click(screen.getByRole("button", { name: "Use extracted value" }));
    expect(number).toHaveValue("SYNTHETIC456");
  });

  it("blocks approval, verification retry and re-extraction while another action is saving", () => {
    render(<ReviewFieldsCard {...props({ isSaving: true })} />);
    expect(screen.getByRole("button", { name: "Approving and saving corrections" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Retry AI Verification" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Re-extract Passport" })).toBeDisabled();
  });

  it("hides obsolete AI decision details after a staff edit", async () => {
    const value = props();
    value.passport = { ...value.passport, post_submission_verified_at: "2026-01-01T12:00:00Z",
      post_submission_verification: { stale_after_staff_edit: true, explanation: "obsolete verification result", verification_status: "ai_approved" } as PassportSubmission["post_submission_verification"] };
    render(<ReviewFieldsCard {...value} />);
    expect(screen.queryByText("obsolete verification result")).not.toBeInTheDocument();
    expect(screen.queryByText("AI decision")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/previous AI verification is no longer/)).toBeVisible());
  });
});
