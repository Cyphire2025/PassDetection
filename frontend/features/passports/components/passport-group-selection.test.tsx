import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { usePassportGroupController } from "./use-passport-group-controller";

const fixture = vi.hoisted(() => ({
  view: {
    total: 1502, total_pages: 31,
    items: [] as Array<{ id: string; extraction_revision: number }>,
    ordered_submission_ids: [] as string[],
    ordered_selection_snapshot: [] as Array<{ submission_id: string; extraction_revision: number }>,
  },
  mutation: { isPending: false, mutate: vi.fn() },
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("../hooks/use-passports", () => ({
  useGroupSubmissionsView: () => ({ data: fixture.view, isLoading: false, isFetching: false }),
  usePassportGroups: () => ({ data: [] }),
  ...Object.fromEntries([
    "useBulkDeletePassportSubmissions", "useBulkStaffApprovePassportSubmissions", "useExportPassportGroup",
    "useExportPassportGroupImages", "useExportSelectedPassportImages", "useExportSelectedPassports",
    "useImportPassportGroup", "usePreviewPassportDocuments", "useSavePassportDocuments",
  ].map((name) => [name, () => fixture.mutation])),
}));
vi.mock("../hooks/use-upload-links", () => ({ useUploadLinks: () => ({ data: [] }), useUpdateUploadLink: () => fixture.mutation }));
vi.mock("./passport-group-bindings", () => ({ MAX_BULK_SELECTION: 1500, MAX_SELECTED_IMAGE_DOWNLOAD: 500 }));
vi.mock("./use-passport-document-follow-up", () => ({ usePassportDocumentFollowUp: () => ({ canManage: true }) }));

beforeEach(() => {
  useAuthStore.setState({ user: { id: "staff", role: "agency_admin", agency_id: "agency" } as User });
  fixture.view.ordered_submission_ids = Array.from({ length: 1502 }, (_, index) => `record-${index}`);
  fixture.view.ordered_selection_snapshot = fixture.view.ordered_submission_ids.map((submission_id, index) => ({ submission_id, extraction_revision: index + 1 }));
  fixture.view.items = [{ id: "record-0", extraction_revision: 99 }];
});

describe("passport group selection state", () => {
  it("applies repeated same-turn toggles to the latest selection", () => {
    const { result } = renderHook(() => usePassportGroupController({ groupId: "group" }));
    act(() => { result.current.togglePassport("record-0"); result.current.togglePassport("record-0"); });
    expect(result.current.selectedPassports).toEqual([]);
    expect(result.current.selectedPassportRevisions).toEqual({});
  });

  it("keeps the cap when two additions occur before rerendering", () => {
    const { result } = renderHook(() => usePassportGroupController({ groupId: "group" }));
    act(() => result.current.setSelectedPassports(fixture.view.ordered_submission_ids.slice(0, 1499)));
    act(() => { result.current.togglePassport("record-1499"); result.current.togglePassport("record-1500"); });
    expect(result.current.selectedPassports).toHaveLength(1500);
    expect(result.current.selectedPassports.at(-1)).toBe("record-1499");
    expect(result.current.selectedPassportRevisions).not.toHaveProperty("record-1500");
    expect(result.current.bulkDeleteFeedback).toMatchObject({ tone: "warning", message: "Select at most 1,500 submissions at a time." });
  });

  it("rejects a decimal custom count instead of selecting its integer prefix", () => {
    const { result } = renderHook(() => usePassportGroupController({ groupId: "group" }));
    act(() => result.current.setCustomSelectionCount("1.5"));
    expect(result.current.customSelectionIsValid).toBe(false);
  });

  it("preserves manual selections beyond the preset and uses authoritative revision snapshots", () => {
    const { result } = renderHook(() => usePassportGroupController({ groupId: "group" }));
    act(() => result.current.togglePassport("record-100"));
    act(() => result.current.selectFirstPassports(2));
    expect(result.current.selectedPassports).toEqual(["record-100", "record-0", "record-1"]);
    expect(result.current.selectedPassportRevisions).toEqual({ "record-100": 101, "record-0": 99, "record-1": 2 });
    act(() => result.current.resetBulkSelection());
    expect(result.current.selectedPassports).toEqual([]);
    expect(result.current.selectedPassportRevisions).toEqual({});
  });

  it("retains revisions only for preset additions admitted below the cap", () => {
    const { result, rerender } = renderHook(() => usePassportGroupController({ groupId: "group" }));
    act(() => result.current.setSelectedPassports(fixture.view.ordered_submission_ids.slice(0, 1499)));
    fixture.view.ordered_submission_ids = Array.from({ length: 50 }, (_, index) => `filtered-${index}`);
    fixture.view.ordered_selection_snapshot = fixture.view.ordered_submission_ids.map((submission_id) => ({ submission_id, extraction_revision: 7 }));
    fixture.view.items = [];
    rerender();
    act(() => result.current.selectFirstPassports(50));
    expect(result.current.selectedPassports).toHaveLength(1500);
    expect(result.current.selectedPassports.at(-1)).toBe("filtered-0");
    expect(result.current.selectedPassportRevisions).toEqual({ "filtered-0": 7 });
  });
});
