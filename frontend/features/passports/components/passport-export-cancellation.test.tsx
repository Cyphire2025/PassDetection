import type { ComponentProps } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PassportGroupDialogs } from "./passport-group-dialogs";

vi.mock("../hooks/use-passports", () => ({
  usePassportGroupExportHistory: () => ({
    data: { total_count: 0, current_submission_count: 2, items: [], total_pages: 0 },
    isLoading: false,
  }),
  usePassportGroupExportFields: () => ({
    data: {
      fields: [],
      grouping_fields: [],
      default_selected_fields: [],
      default_group_by_field: null,
      agency_match_enabled: false,
    },
    isLoading: false,
  }),
  usePassportGroupExportHistoryDetail: () => ({}),
}));

vi.mock("./passport-group-bindings", async () => ({
  PassportExportDialog: (await import("./passport-export-dialog")).PassportExportDialog,
  PassportImageCropEditor: () => null,
  TripDetailsDialog: () => null,
}));

describe("passport export Save As cancellation", () => {
  it("keeps options open without an error and allows another download after cancellation", async () => {
    const mutateAsync = vi.fn()
      .mockRejectedValueOnce(new DOMException("User cancelled", "AbortError"))
      .mockResolvedValueOnce(undefined);
    const setExportDialogKind = vi.fn();
    const setImportMessage = vi.fn();
    const props = {
      groupId: "group-1",
      groupDetails: { group_name: "September Group" },
      exportDialogKind: "passport_excel",
      exportMutation: { mutateAsync, isPending: false },
      exportImagesMutation: { isPending: false },
      setExportDialogKind,
      setImportMessage,
      selectedPassports: [],
      bulkStaffApprove: { isPending: false },
      bulkDelete: { isPending: false },
    } as unknown as ComponentProps<typeof PassportGroupDialogs>;
    render(<PassportGroupDialogs {...props} />);

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Download Excel" }));
    await waitFor(() => {
      expect(mutateAsync).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("button", { name: "Download Excel" })).toBeEnabled();
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(setExportDialogKind).not.toHaveBeenCalled();
    expect(setImportMessage).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Download Excel" }));
    await waitFor(() => expect(setExportDialogKind).toHaveBeenCalledWith(null));
    expect(mutateAsync).toHaveBeenCalledTimes(2);
    expect(mutateAsync.mock.calls[1][0]).toMatchObject({
      groupId: "group-1",
      groupName: "September Group",
    });
  });
});
