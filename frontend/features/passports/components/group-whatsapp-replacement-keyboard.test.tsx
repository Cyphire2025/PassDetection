import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GroupWhatsAppMatch, ReplacementCandidate } from "../api/upload-links.api";
import { ReplacementDialog } from "./group-whatsapp-dialogs";

const fixture = vi.hoisted(() => ({ mutate: vi.fn(), available: [] as ReplacementCandidate[] }));
const candidates: ReplacementCandidate[] = ["Alpha", "Beta", "Gamma"].map((name, index) => ({
  recipient_id: `recipient-${index}`, recipient_ids: [`recipient-${index}`],
  name, phone: `+91900000000${index}`, broadcast_ids: ["broadcast"],
  broadcast_names: ["Synthetic roster"], imported_fields: { producer_code: `CODE-${index}` },
}));
vi.mock("../hooks/use-upload-links", () => ({
  useReplacementCandidates: () => ({ data: { items: fixture.available }, isLoading: false }),
  useResolveUnidentifiedReplacement: () => ({ mutate: fixture.mutate, isPending: false }),
  useUpdateGroupWhatsAppLinks: vi.fn(),
}));
const row: GroupWhatsAppMatch = {
  status: "unmatched_submission", match_basis: null, normalized_phone: null,
  recipient_ids: [], submission_ids: ["submission"], broadcast_ids: [], broadcast_names: [],
  recipient_names: [], submission_names: ["New traveller"], confidence: "none",
  match_evidence: [], candidate_submission_ids: [], recipient_fields: [], submission_details: [],
  resolution_id: null, updated_at: null,
};
beforeEach(() => { fixture.mutate.mockReset(); fixture.available = candidates; });

describe("replacement recipient keyboard selection", () => {
  it("moves and selects the next recipient using native radio arrow keys", async () => {
    render(<ReplacementDialog groupId="group" row={row} onClose={vi.fn()} onResolved={vi.fn()} />);
    const choices = screen.getAllByRole("radio");
    choices[0].focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(choices[1]).toHaveFocus();
    expect(choices[1]).toBeChecked();
    await userEvent.keyboard("{ArrowUp}");
    expect(choices[0]).toHaveFocus();
    expect(choices[0]).toBeChecked();
    expect(screen.getByRole("button", { name: "Confirm replacement" })).toBeEnabled();
  });

  it("preserves the chosen recipient and idempotency request ID through a failed save", async () => {
    fixture.mutate.mockImplementationOnce((_request, options) => options.onError());
    render(<ReplacementDialog groupId="group" row={row} onClose={vi.fn()} onResolved={vi.fn()} />);
    await userEvent.click(screen.getAllByRole("radio")[1]);
    await userEvent.click(screen.getByRole("button", { name: "Confirm replacement" }));
    expect(screen.getByRole("alert")).toHaveTextContent("replacement could not be saved");
    await userEvent.click(screen.getByRole("button", { name: "Confirm replacement" }));
    expect(fixture.mutate).toHaveBeenCalledTimes(2);
    const first = fixture.mutate.mock.calls[0][0];
    expect(first).toMatchObject({ submissionId: "submission", recipientId: "recipient-1", requestId: expect.any(String) });
    expect(fixture.mutate.mock.calls[1][0]).toEqual(first);
  });

  it("requires a current recipient if a refresh removes the selected person", async () => {
    const props = { groupId: "group", row, onClose: vi.fn(), onResolved: vi.fn() };
    const { rerender } = render(<ReplacementDialog {...props} />);
    await userEvent.click(screen.getAllByRole("radio")[1]);
    expect(screen.getByRole("button", { name: "Confirm replacement" })).toBeEnabled();
    fixture.available = candidates.filter((candidate) => candidate.recipient_id !== "recipient-1");
    rerender(<ReplacementDialog {...props} />);
    const confirm = screen.getByRole("button", { name: "Confirm replacement" });
    expect(confirm).toBeDisabled();
    await userEvent.click(confirm);
    expect(fixture.mutate).not.toHaveBeenCalled();
    await userEvent.click(screen.getAllByRole("radio")[0]);
    await userEvent.click(confirm);
    expect(fixture.mutate).toHaveBeenCalledOnce();
    expect(fixture.mutate.mock.calls[0][0]).toMatchObject({ recipientId: "recipient-0" });
  });
});
