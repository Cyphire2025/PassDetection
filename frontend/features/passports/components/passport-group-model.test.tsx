import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { buildPassportDetailNavigationHref, parsePassportGroupViewState } from "../utils/passport-group-navigation";
import type { ComponentProps } from "react";
import { PassportMobileCard, ReextractPassportControl } from "./passport-group-model";
import { PassportGroupRosterPanel } from "./passport-group-roster-panel";

const mutation = vi.hoisted(() => ({ mutateAsync: vi.fn(), isPending: false }));
vi.mock("../hooks/use-passports", () => ({ useReextractPassportSubmission: () => mutation }));
const passport = {
  id: "record", client_name: "Synthetic passenger", client_email: "synthetic@example.test",
  image_s3_key: "private/synthetic.jpg", status: "needs_review", extraction_status: "ready_for_review",
  updated_at: "2026-10-31T00:00:00Z", post_submission_verification: {
    provider_status: "verified", incorrect_fields: ["surname", "given_names", "passport_number", "nationality"],
  },
} as PassportSubmission;
const detailHref = (id = passport.id) => buildPassportDetailNavigationHref(id, {
  token: null, groupId: "group", includeDeleted: false,
  viewState: parsePassportGroupViewState(new URLSearchParams()),
});
beforeEach(() => { vi.resetAllMocks(); mutation.isPending = false; });

describe("passport group row controls", () => {
  it("provides one navigation control without nesting an interactive button inside its link", () => {
    const onToggle = vi.fn(), onOpen = vi.fn();
    render(<PassportMobileCard passport={{ ...passport, status: "staff_approved" }} selected={false} onToggle={onToggle} onOpen={onOpen} detailHref={detailHref()} />);
    const link = screen.getByRole("link", { name: "Open Submission" });
    expect(within(link).queryByRole("button")).not.toBeInTheDocument();
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("allows retry after a failed start for an eligible review record", async () => {
    mutation.mutateAsync.mockRejectedValueOnce(new Error("Synthetic temporary failure"));
    mutation.mutateAsync.mockResolvedValueOnce({ outcome: "completed", submission: { ...passport, status: "ai_approved" } });
    render(<ReextractPassportControl passport={passport} />);
    fireEvent.click(screen.getByRole("button", { name: "Re-extract" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Synthetic temporary failure");
    const retry = screen.getByRole("button", { name: "Try again" });
    expect(retry).toBeEnabled();
    fireEvent.click(retry);
    await screen.findByText("Re-extraction and AI verification finished. All passport fields passed verification.");
    expect(mutation.mutateAsync).toHaveBeenCalledTimes(2);
  });

  it("continues blocking a second extraction while submitted verification remains pending after polling times out", async () => {
    let finish!: (value: unknown) => void;
    mutation.mutateAsync.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const { rerender } = render(<ReextractPassportControl passport={passport} />);
    fireEvent.click(screen.getByRole("button", { name: "Re-extract" }));
    await waitFor(() => expect(mutation.mutateAsync).toHaveBeenCalledOnce());
    rerender(<ReextractPassportControl passport={{ ...passport, status: "submitted", extraction_status: "extraction_complete" }} />);
    await act(async () => finish({ outcome: "timed_out", submission: { ...passport, status: "submitted" } }));
    expect(screen.getByRole("button", { name: "Processing" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Still processing");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("keeps the desktop workspace link as one interactive control without toggling its row", () => {
    const completed = { ...passport, status: "staff_approved" } as PassportSubmission;
    const togglePassport = vi.fn(), persistNavigationContext = vi.fn();
    const props = {
      error: null, isLoading: false, isFetching: false, groupDetails: undefined,
      submissionsView: { items: [completed], ordered_submission_ids: [completed.id], ordered_selection_snapshot: [], group_total: 1, total: 1, page: 1, page_size: 50, total_pages: 1, returned_count: 1, cluster_boundaries_preserved: false, expiry_alerts: [] },
      data: [completed], filteredPassports: [completed], setSearch: vi.fn(), setDebouncedSearch: vi.fn(),
      setSubmissionFilter: vi.fn(), setSortBy: vi.fn(), setSortOrder: vi.fn(), setPage: vi.fn(),
      viewMode: "table", canEditImages: false, includeDeleted: false, imageRevisions: {},
      setImageEditor: vi.fn(), debouncedSearch: "", selectedPassportIdSet: new Set<string>(),
      togglePassport, passportDetailHref: detailHref,
      persistNavigationContext, page: 1,
    } satisfies ComponentProps<typeof PassportGroupRosterPanel>;
    render(<PassportGroupRosterPanel {...props} />);
    const link = screen.getByRole("link", { name: "Open" });
    expect(within(link).queryByRole("button")).not.toBeInTheDocument();
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    expect(persistNavigationContext).toHaveBeenCalledOnce();
    expect(togglePassport).not.toHaveBeenCalled();
  });
});
