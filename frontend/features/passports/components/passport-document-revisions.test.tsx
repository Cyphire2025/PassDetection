import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { PassportGroupDialogs } from "./passport-group-dialogs";
import { PassportGroupRosterPanel } from "./passport-group-roster-panel";
import { usePassportGroupController } from "./use-passport-group-controller";

const { refetch, idleMutation, submissions } = vi.hoisted(() => ({
  refetch: vi.fn(),
  idleMutation: { mutate: vi.fn(), isPending: false },
  submissions: ["Alice", "Bob"].map((name) => ({
    id: name.toLowerCase(), client_name: name, extracted_fields: null, confirmed_fields: null,
    passport_photo_url: `/${name}/photo`, image_url: `/${name}/front`,
    passport_back_url: `/${name}/back`, passport_cover_url: `/${name}/cover`,
    passport_back_cover_url: `/${name}/back-cover`, extraction_revision: 1,
  })),
}));

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams("view=docs") }));
vi.mock("../hooks/use-passports", () => ({
  useGroupSubmissionsView: () => ({
    data: { items: submissions, group_total: 2, total: 2, page: 1, total_pages: 1, ordered_submission_ids: ["alice", "bob"] },
    isLoading: false, isFetching: false, refetch,
  }),
  usePassportGroups: () => ({ data: [] }),
  useBulkDeletePassportSubmissions: () => idleMutation,
  useBulkStaffApprovePassportSubmissions: () => idleMutation,
  useBulkDocumentFollowUp: () => idleMutation,
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
  TripDetailsDialog: () => null,
  PassportImageCropEditor: ({ onSaved, onClose }: { onSaved: () => void; onClose: () => void }) => (
    <button onClick={() => { onSaved(); onClose(); }}>Save crop</button>
  ),
}));
vi.mock("./passport-document-cell", () => ({
  DocumentCell: ({ label, revision, onEdit }: {
    label: string; revision: number; onEdit: (trigger: HTMLButtonElement) => void;
  }) => (
    <td data-revision={revision}>
      <button onClick={(event) => onEdit(event.currentTarget)}>Edit {label}</button>
    </td>
  ),
}));

function DocumentsHarness() {
  const controller = usePassportGroupController({ groupId: "group-1" });
  return <><PassportGroupRosterPanel {...controller} /><PassportGroupDialogs {...controller} /></>;
}

beforeEach(() => {
  refetch.mockClear();
  useAuthStore.setState({
    user: { id: "admin", role: "super_admin", agency_id: "agency-1", is_active: true } as User,
    isAuthenticated: true, hasHydrated: true,
  });
});

it("saving a document refreshes only that passenger's edited image across repeated saves", () => {
  render(<DocumentsHarness />);
  const alice = screen.getByRole("row", { name: /Alice/ });
  const bob = screen.getByRole("row", { name: /Bob/ });
  const revisions = (row: HTMLElement) => within(row).getAllByRole("cell").slice(1)
    .map((cell) => cell.getAttribute("data-revision"));

  expect(revisions(alice)).toEqual(["0", "0", "0", "0", "0"]);
  expect(revisions(bob)).toEqual(["0", "0", "0", "0", "0"]);
  fireEvent.click(within(alice).getByRole("button", { name: "Edit Passport Back Cover" }));
  fireEvent.click(screen.getByRole("button", { name: "Save crop" }));
  expect(revisions(alice)).toEqual(["0", "0", "0", "0", "1"]);
  expect(revisions(bob)).toEqual(["0", "0", "0", "0", "0"]);

  fireEvent.click(within(bob).getByRole("button", { name: "Edit Passport front" }));
  fireEvent.click(screen.getByRole("button", { name: "Save crop" }));
  expect(revisions(alice)).toEqual(["0", "0", "0", "0", "1"]);
  expect(revisions(bob)).toEqual(["0", "1", "0", "0", "0"]);

  fireEvent.click(within(alice).getByRole("button", { name: "Edit Passport Back Cover" }));
  fireEvent.click(screen.getByRole("button", { name: "Save crop" }));
  expect(revisions(alice)).toEqual(["0", "0", "0", "0", "2"]);
  expect(revisions(bob)).toEqual(["0", "1", "0", "0", "0"]);
  expect(refetch).toHaveBeenCalledTimes(3);
});
