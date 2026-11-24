import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { GroupWhatsAppLinksResponse, GroupWhatsAppMatchesResponse } from "../api/upload-links.api";
import { GroupWhatsAppBroadcastPanel, GroupWhatsAppBroadcastTrackingPage } from "./group-whatsapp-broadcast-panel";

const fixture = vi.hoisted(() => ({
  matches: vi.fn(), resetExport: vi.fn(), export: vi.fn(), canManage: true, importOnly: false,
  router: { replace: vi.fn(), prefetch: vi.fn() },
}));
const links: GroupWhatsAppLinksResponse = {
  client_group_id: "group", broadcast_count: 2, recipient_count: 2, can_manage: true,
  broadcasts: ["one", "two"].map((id) => ({ id: `broadcast-${id}`, name: `Synthetic ${id}`, recipient_count: 1, created_at: "2026-10-31T00:00:00Z", updated_at: "2026-10-31T00:00:00Z", matching_field_keys: ["phone"] })),
};
const matches: GroupWhatsAppMatchesResponse = {
  client_group_id: "group", selected_broadcast_id: null, linked_broadcast_count: 2,
  counts: { total_recipients: 2, submitted_count: 0, not_submitted_count: 2, multiple_submission_count: 0, matched_submission_count: 0, needs_review_count: 0, needs_review_submission_count: 0, unmatched_submission_count: 0, replacement_count: 0, rejected_upload_count: 0 },
  matches: [{ status: "not_submitted", match_basis: null, normalized_phone: "+919000000000", recipient_ids: ["recipient"], submission_ids: [], broadcast_ids: ["broadcast-one"], broadcast_names: ["Synthetic one"], recipient_names: ["Synthetic recipient"], submission_names: [], confidence: "none", match_evidence: [], candidate_submission_ids: [], recipient_fields: [], submission_details: [], resolution_id: null, updated_at: null }],
  total: 1, page: 1, page_size: 50, total_pages: 1,
};
vi.mock("next/navigation", () => ({ useRouter: () => fixture.router }));
vi.mock("../hooks/use-passports", () => ({
  usePassportGroups: () => ({ data: [{ group_id: "group", import_only: fixture.importOnly }], isLoading: false, isError: false }),
  useExportWhatsAppTracking: () => ({ reset: fixture.resetExport, mutate: fixture.export, isPending: false, error: null }),
}));
vi.mock("../hooks/use-upload-links", () => ({
  useGroupWhatsAppLinks: () => ({ data: { ...links, can_manage: fixture.canManage }, isLoading: false, error: null }),
  useGroupWhatsAppMatches: (...args: unknown[]) => fixture.matches(...args),
  useRejectUnidentifiedUpload: () => ({ isPending: false }),
  useRestoreRosterResolution: () => ({ isPending: false }),
}));
beforeEach(() => {
  vi.clearAllMocks(); fixture.canManage = true; fixture.importOnly = false;
  fixture.matches.mockReturnValue({ data: matches, isLoading: false, isFetching: false, error: null });
  useAuthStore.setState({ user: { id: "staff", role: "agency_admin", agency_id: "agency" } as User, hasHydrated: true });
});

describe("group broadcast workspace contracts", () => {
  it("keeps status and broadcast scope aligned with the exported view", () => {
    render(<GroupWhatsAppBroadcastTrackingPage groupId="group" />);
    expect(screen.getByRole("heading", { name: "WhatsApp Submission Tracking" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Needs review" }));
    fireEvent.change(screen.getByLabelText("Broadcast"), { target: { value: "broadcast-two" } });
    expect(fixture.matches).toHaveBeenLastCalledWith("group", expect.objectContaining({ status: "needs_review", broadcast_id: "broadcast-two", page: 1, page_size: 50 }), true);
    fireEvent.click(screen.getByRole("button", { name: "Export Needs review to Excel" }));
    expect(fixture.resetExport).toHaveBeenCalledOnce();
    expect(fixture.export).toHaveBeenCalledExactlyOnceWith({ groupId: "group", status: "needs_review", broadcastId: "broadcast-two" });
  });

  it("does not enable submission comparisons in the compact read-only summary", () => {
    render(<GroupWhatsAppBroadcastPanel groupId="group" readOnly />);
    expect(fixture.matches).toHaveBeenLastCalledWith("group", expect.any(Object), false);
    expect(screen.queryByRole("button", { name: "Manage broadcasts" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View tracking" })).toHaveAttribute("href", "/passports/groups/group/whatsapp");
  });

  it("uses the server management decision for tracking actions", () => {
    fixture.canManage = false;
    render(<GroupWhatsAppBroadcastTrackingPage groupId="group" />);
    expect(screen.queryByRole("button", { name: "Manage broadcasts" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Action" })).not.toBeInTheDocument();
  });

  it("blocks import-only groups before mounting private comparison observers", () => {
    fixture.importOnly = true;
    render(<GroupWhatsAppBroadcastTrackingPage groupId="group" />);
    expect(fixture.router.replace).toHaveBeenCalledWith("/passports/groups/group");
    expect(fixture.matches).not.toHaveBeenCalled();
  });

  it("redirects a coordinator without mounting private tracking observers", () => {
    useAuthStore.setState({ user: { id: "coordinator", role: "agency_coordinator", agency_id: "agency" } as User });
    render(<GroupWhatsAppBroadcastTrackingPage groupId="group" />);
    expect(fixture.router.replace).toHaveBeenCalledWith("/coordinator");
    expect(fixture.matches).not.toHaveBeenCalled();
  });
});
