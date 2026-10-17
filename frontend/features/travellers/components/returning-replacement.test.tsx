import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { returningApi } from "../api/returning.api";
import type { ReplacementIntent, ReturningHistory } from "../types";
import { ReturningReplacementStatus } from "./returning-replacement-status";
import { ReturningUpdateDialog } from "./returning-update-dialog";

vi.mock("../api/returning.api", () => ({ returningApi: { replacement: vi.fn() } }));
const intent: ReplacementIntent = { reviewVersion: "opaque-reviewed-version", displayName: "Selected Traveller", changeKind: "renewal", idempotencyKey: "same-operation-identity", uploadSessionId: "new-upload-session" };
const submission = { id: "newly-submitted-document", extraction_revision: 5, status: "needs_review" } as PassportSubmission;
beforeEach(() => vi.clearAllMocks());
describe("selected traveller replacement", () => {
  it("requires an explicit change kind and forwards the displayed review binding", () => {
    const onContinue = vi.fn();
    render(<ReturningUpdateDialog history={{ review_version: intent.reviewVersion, display_name: intent.displayName } as ReturningHistory} onClose={vi.fn()} onContinue={onContinue} />);
    expect(screen.getByRole("button", { name: "Continue to updated document" })).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "A renewed or replacement passport" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue to updated document" }));
    expect(onContinue).toHaveBeenCalledExactlyOnceWith({ reviewVersion: intent.reviewVersion, displayName: intent.displayName, changeKind: "renewal" });
  });
  it("associates only the actual new submission and retries without uploading again or accepting it", async () => {
    vi.mocked(returningApi.replacement).mockRejectedValueOnce(new Error("Connection lost")).mockResolvedValueOnce({ status: "candidate_pending_review", match_case_id: "case" });
    render(<ReturningReplacementStatus intent={intent} submission={submission} />);
    await screen.findByRole("alert");
    expect(screen.getByRole("heading", { name: "Updated document submitted" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Retry traveller association" }));
    await screen.findByText(/awaiting staff review/);
    const calls = vi.mocked(returningApi.replacement).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0][0]).toEqual(calls[1][0]);
    expect(calls[0]).toEqual([{ source_submission_id: submission.id, expected_extraction_revision: 5, review_version: intent.reviewVersion, change_kind: "renewal", idempotency_key: intent.idempotencyKey }, "new-upload-session", expect.any(AbortSignal)]);
  });
  it("aborts association on exit and does not treat expired proof as accepted renewal", async () => {
    vi.mocked(returningApi.replacement).mockImplementation(() => new Promise(() => undefined));
    const view = render(<ReturningReplacementStatus intent={intent} submission={submission} />);
    await waitFor(() => expect(returningApi.replacement).toHaveBeenCalled());
    const signal = vi.mocked(returningApi.replacement).mock.calls[0][2];
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
