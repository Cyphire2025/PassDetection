import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User, UserRole } from "@/types";
import { PassportGroupDialogs } from "./passport-group-dialogs";
import { PassportGroupSelectionToolbar } from "./passport-group-selection-toolbar";
import { usePassportGroupController } from "./use-passport-group-controller";

const { bulkDelete, idleMutation, submissionsView } = vi.hoisted(() => ({
  bulkDelete: { mutate: vi.fn(), isPending: false },
  idleMutation: { mutate: vi.fn(), isPending: false },
  submissionsView: {
    data: {
      items: [{ id: "submission-1", extraction_revision: 1 }],
      total: 1,
      total_pages: 1,
      ordered_submission_ids: ["submission-1"],
    },
    isLoading: false,
    isFetching: false,
    refetch: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("../hooks/use-passports", () => ({
  useGroupSubmissionsView: () => submissionsView,
  usePassportGroups: () => ({ data: [] }),
  useBulkDeletePassportSubmissions: () => bulkDelete,
  useBulkStaffApprovePassportSubmissions: () => idleMutation,
  useExportPassportGroup: () => idleMutation,
  useExportPassportGroupImages: () => idleMutation,
  useExportSelectedPassportImages: () => idleMutation,
  useExportSelectedPassports: () => idleMutation,
  useImportPassportGroup: () => idleMutation,
  usePreviewPassportDocuments: () => idleMutation,
  useSavePassportDocuments: () => idleMutation,
}));
vi.mock("../hooks/use-upload-links", () => ({
  useUpdateUploadLink: () => idleMutation,
  useUploadLinks: () => ({ data: [] }),
}));
vi.mock("./passport-group-bindings", () => ({
  MAX_BULK_SELECTION: 1500,
  MAX_SELECTED_IMAGE_DOWNLOAD: 500,
  PassportExportDialog: () => null,
  PassportImageCropEditor: () => null,
  TripDetailsDialog: () => null,
}));

function GroupActionsHarness() {
  const controller = usePassportGroupController({ groupId: "group-1" });
  return <>
    <button onClick={() => controller.togglePassport("submission-1")}>Select passenger</button>
    <span>{controller.canAccessWhatsApp ? "WhatsApp available" : "WhatsApp unavailable"}</span>
    <PassportGroupSelectionToolbar {...controller} />
    <PassportGroupDialogs {...controller} />
  </>;
}

function signIn(role: UserRole) {
  useAuthStore.setState({
    user: { id: `${role}-1`, role, agency_id: "agency-1", is_active: true } as User,
    isAuthenticated: true,
    hasHydrated: true,
  });
}

beforeEach(() => {
  bulkDelete.mutate.mockReset();
  useAuthStore.setState({ user: null, isAuthenticated: false, hasHydrated: false });
});

describe("group action role permissions", () => {
  it.each(["super_admin", "agency_admin", "agency_manager"] as const)("lets %s delete a selected submission after confirmation", (role) => {
    signIn(role);
    render(<GroupActionsHarness />);
    fireEvent.click(screen.getByRole("button", { name: "Select passenger" }));
    fireEvent.click(screen.getByRole("button", { name: "Open bulk actions for 1 selected submissions" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete selected (1)" }));
    expect(screen.getByRole("dialog")).toHaveTextContent("Delete selected submissions?");
    expect(bulkDelete.mutate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete 1 submission" }));
    expect(bulkDelete.mutate).toHaveBeenCalledWith(["submission-1"], expect.any(Object));
  });

  it("keeps staff WhatsApp and approval access while hiding submission deletion", () => {
    signIn("agency_staff");
    render(<GroupActionsHarness />);
    expect(screen.getByText("WhatsApp available")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select passenger" }));
    fireEvent.click(screen.getByRole("button", { name: "Open bulk actions for 1 selected submissions" }));
    expect(screen.getByRole("button", { name: "Staff approve all selected (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete selected/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(bulkDelete.mutate).not.toHaveBeenCalled();
  });
});
