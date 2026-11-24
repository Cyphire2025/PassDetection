import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PassportGroupExportFieldOptions, PassportGroupExportHistory, PassportGroupExportHistoryDetail } from "../api/passports.api";
import { PassportExportDialog } from "./passport-export-dialog";

const fixture = vi.hoisted(() => ({
  history: undefined as unknown as PassportGroupExportHistory,
  detail: undefined as unknown as PassportGroupExportHistoryDetail,
  fields: undefined as unknown as PassportGroupExportFieldOptions,
  fetching: false,
  historyQuery: vi.fn(), detailQuery: vi.fn(),
}));
vi.mock("../hooks/use-passports", () => ({
  usePassportGroupExportHistory: (...args: unknown[]) => { fixture.historyQuery(...args); return { data: fixture.history, isLoading: false, isFetching: fixture.fetching }; },
  usePassportGroupExportHistoryDetail: (...args: unknown[]) => { fixture.detailQuery(...args); return { data: fixture.detail, isLoading: false }; },
  usePassportGroupExportFields: () => ({ data: fixture.fields, isLoading: false }),
}));
beforeEach(() => {
  fixture.fetching = false; fixture.historyQuery.mockClear(); fixture.detailQuery.mockClear();
  fixture.history = { group_id: "group", export_kind: "passport_images", current_submission_count: 4, page: 1, page_size: 25, total_pages: 2, total_count: 26, items: [
    { id: "checkpoint", export_kind: "passport_images", export_mode: "all", baseline_export_id: null, compatible: true, new_submission_count: 1, changed_submission_count: 2, removed_submission_count: 1, total_available_count: 4, exported_count: 4, pending_recipient_count: 0, actor_email: "reviewer@example.test", created_at: "2026-10-01T10:00:00Z", completed_at: "2026-10-01T10:01:00Z" },
  ] };
  fixture.detail = { history_id: "checkpoint", group_id: "group", export_kind: "passport_images", created_at: "2026-10-01T10:00:00Z", completed_at: "2026-10-01T10:01:00Z", exported_count: 4, page: 1, page_size: 25, total_pages: 2, items: [{ submission_id: "removed", client_name: "Synthetic removed record", client_phone: null, client_email: null, passport_number: "SYNTHETIC", record_available: false }] };
  fixture.fields = { group_id: "group", fields: [{ key: "email", label: "Saved email", source: "whatsapp", selected_by_default: true }], grouping_fields: [{ key: "none", label: "No grouping", fixed: true }], default_selected_fields: ["email"], default_group_by_field: "none", agency_match_enabled: false, agency_match_fields: [] };
});

const show = (kind: "passport_images" | "passport_excel" = "passport_images", onDownload = vi.fn().mockResolvedValue(undefined), onClose = vi.fn()) => ({ ...render(<PassportExportDialog groupId="group" kind={kind} isDownloading={false} onDownload={onDownload} onClose={onClose} />), onDownload, onClose });
const incremental = () => fireEvent.click(screen.getByRole("radio", { name: /Download changes since/ }));

describe("passport export option safety and history", () => {
  it("requires a compatible checkpoint with changes before incremental export", async () => {
    fixture.history.items[0].compatible = false;
    const view = show(); incremental();
    const baseline = screen.getByRole("radio", { name: /uploads existed/ });
    expect(baseline).toBeDisabled(); expect(screen.getByRole("button", { name: "Download changes" })).toBeDisabled();
    expect(view.onDownload).not.toHaveBeenCalled();
    fixture.history.items[0].compatible = true;
    view.rerender(<PassportExportDialog groupId="group" kind="passport_images" isDownloading={false} onDownload={view.onDownload} onClose={view.onClose} />);
    fireEvent.click(baseline);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Download changes" })));
    expect(view.onDownload).toHaveBeenCalledExactlyOnceWith({ mode: "incremental", baselineExportId: "checkpoint" });
  });

  it("keeps a zero-change checkpoint ineligible without silently falling back to all", () => {
    Object.assign(fixture.history.items[0], { new_submission_count: 0, changed_submission_count: 0, removed_submission_count: 0 });
    const { onDownload } = show(); incremental();
    fireEvent.click(screen.getByRole("radio", { name: /uploads existed/ }));
    fireEvent.click(screen.getByRole("button", { name: "Download changes" }));
    expect(onDownload).not.toHaveBeenCalled();
  });

  it("retains deleted-source history snapshots and paginates people independently", () => {
    show(); incremental();
    fireEvent.click(screen.getByRole("button", { name: "View downloaded people" }));
    expect(screen.getByText("Synthetic removed record")).toBeInTheDocument();
    expect(screen.getByText(/Original record later deleted/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next history detail page" }));
    expect(fixture.detailQuery).toHaveBeenLastCalledWith("group", "checkpoint", 2);
    expect(fixture.historyQuery).toHaveBeenLastCalledWith("group", "passport_images", 1);
    fireEvent.click(screen.getByRole("button", { name: "Hide downloaded people" }));
    fireEvent.click(screen.getByRole("button", { name: "View downloaded people" }));
    expect(fixture.detailQuery).toHaveBeenLastCalledWith("group", "checkpoint", 1);
  });

  it("bounds history paging and prevents duplicate page advances during a fetch", () => {
    const view = show(); incremental();
    expect(screen.getByRole("button", { name: "Newer download history page" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Older download history page" }));
    expect(fixture.historyQuery).toHaveBeenLastCalledWith("group", "passport_images", 2);
    expect(screen.getByRole("button", { name: "Older download history page" })).toBeDisabled();
    fixture.fetching = true;
    view.rerender(<PassportExportDialog groupId="group" kind="passport_images" isDownloading={false} onDownload={view.onDownload} onClose={view.onClose} />);
    expect(screen.getByRole("button", { name: "Newer download history page" })).toBeDisabled();
  });

  it("uses one same-turn download and prevents dismissal until it settles", async () => {
    let finish!: () => void;
    const onDownload = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    const { onClose } = show("passport_images", onDownload);
    const button = screen.getByRole("button", { name: "Download all" });
    fireEvent.click(button); fireEvent.click(button);
    expect(onDownload).toHaveBeenCalledOnce();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    for (const control of within(screen.getByRole("dialog")).getAllByRole("button", { name: /Cancel|Close export options/ })) expect(control).toBeDisabled();
    await act(async () => finish());
    expect(button).toBeEnabled();
  });

  it("retains server defaults across the Excel field step and Back", async () => {
    const { onDownload } = show("passport_excel");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { name: "Step 2: Choose Excel columns" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(onDownload).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Download Excel" })));
    expect(onDownload).toHaveBeenCalledExactlyOnceWith({ mode: "all", supplementalFields: ["email"], groupByField: "none", agencyMatchField: undefined });
  });
});
