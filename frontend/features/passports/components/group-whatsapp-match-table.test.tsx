import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { GroupWhatsAppMatch } from "../api/upload-links.api";
import { BroadcastMatchTable } from "./group-whatsapp-tracking-table";

function row(name: string): GroupWhatsAppMatch {
  return {
    status: "unmatched_submission", match_basis: null, normalized_phone: null,
    recipient_ids: [], submission_ids: [name], broadcast_ids: [], broadcast_names: [],
    recipient_names: [], submission_names: [name], confidence: "none", match_evidence: [],
    candidate_submission_ids: [], recipient_fields: [], submission_details: [],
    resolution_id: null, updated_at: null,
  };
}
const actions = () => ({ onMarkReplacement: vi.fn(), onReject: vi.fn(), onRestore: vi.fn() });

describe("group broadcast match rows", () => {
  it("links review candidates without presenting accepted submission IDs as their evidence", () => {
    render(<BroadcastMatchTable rows={[{ ...row("review"), status: "needs_review", submission_ids: ["accepted"], candidate_submission_ids: ["possible"] }]} isLoading={false} error={null} filter="needs_review" canManage={false} isActionPending={false} {...actions()} />);
    expect(screen.getByRole("link", { name: "Open candidate" })).toHaveAttribute("href", "/passports/possible");
    expect(screen.queryByRole("link", { name: "Open submission" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Action" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps focused row identity through sorting and forwards its exact resolution target", () => {
    const first = row("First traveller"), second = row("Second traveller"), callbacks = actions();
    const props = { isLoading: false, error: null, filter: "all" as const, canManage: true, isActionPending: false, ...callbacks };
    const { rerender } = render(<BroadcastMatchTable rows={[first, second]} {...props} />);
    const button = within(screen.getByRole("row", { name: /First traveller/ })).getByRole("button", { name: "Mark as replacement" });
    button.focus();
    rerender(<BroadcastMatchTable rows={[second, first]} {...props} />);
    expect(within(screen.getByRole("row", { name: /First traveller/ })).getByRole("button", { name: "Mark as replacement" })).toBe(button);
    expect(button).toHaveFocus();
    fireEvent.click(button);
    expect(callbacks.onMarkReplacement).toHaveBeenCalledExactlyOnceWith(first);
    rerender(<BroadcastMatchTable rows={[second, first]} {...props} isActionPending />);
    expect(button).toBeDisabled();
  });

  it("presents a comparison error without stale action controls", () => {
    render(<BroadcastMatchTable rows={[row("Old traveller")]} isLoading={false} error={new Error("Synthetic failed")} filter="all" canManage isActionPending={false} {...actions()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Recipient comparison could not be loaded");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
