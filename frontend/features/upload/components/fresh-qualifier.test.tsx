import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UploadLinkResponse, QualifierSelectionState } from "@/features/passports/api/upload-links.api";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import type { DraftQualifierInputs } from "../services/draft-input-contract";
import { FreshQualifier } from "./fresh-qualifier";

const api = vi.hoisted(() => ({ read: vi.fn(), save: vi.fn(), collection: vi.fn() }));
vi.mock("@/features/passports/api/upload-links.api", () => ({ uploadLinksApi: { getQualifierSelection: api.read } }));
const group = { token: "trip", qualifier_relation_options: [{ code: "spouse", label: "Spouse" }], upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, qualifier_relation_list_enabled: true, qualifier_relation_other_enabled: true } } as UploadLinkResponse;
const saved: QualifierSelectionState = { is_self: false, relation_code: "other", relation_label: "Cousin", status: "active", selected_at: "2026-10-01T00:00:00Z", expires_at: "2027-01-01T00:00:00Z", submission_id: null };
function Harness({ token = "saved-choice" }: { token?: string }) {
  const [selection, setSelection] = useState<string | null>(token);
  const state = { pending: false, payload: { collection: { qualifier_selection_token: selection } },
    collection: (patch: { qualifier_selection_token: string | null }) => { api.collection(patch); setSelection(patch.qualifier_selection_token); },
    serialized: async (operation: (signal: AbortSignal) => Promise<unknown>) => operation(new AbortController().signal),
    api: { qualifier: api.save },
  } as unknown as DraftQualifierInputs;
  return <FreshQualifier state={state} group={group} />;
}
beforeEach(() => { vi.clearAllMocks(); api.read.mockResolvedValue(saved); api.save.mockResolvedValue({ selection_token: "new-choice" }); });

describe("private draft qualifier restoration", () => {
  it("loads only on Change, restores Other text, and saves a trimmed replacement", async () => {
    render(<Harness />);
    expect(api.read).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(await screen.findByRole("textbox", { name: "Specify relationship" })).toHaveValue("Cousin");
    expect(api.read).toHaveBeenCalledExactlyOnceWith("trip", "saved-choice", expect.any(AbortSignal));
    expect(screen.getByRole("radio", { name: /Other relationship/ })).toHaveAttribute("aria-checked", "true");
    fireEvent.change(screen.getByRole("textbox", { name: "Specify relationship" }), { target: { value: " Colleague " } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(api.save).toHaveBeenCalledExactlyOnceWith({ is_self: false, relation_code: "other", other_relation: "Colleague" }, expect.any(AbortSignal)));
    expect(api.collection).toHaveBeenCalledWith({ qualifier_selection_token: "new-choice" });
    expect(screen.getByText("Qualifier relationship saved")).toBeVisible();
  });

  it("keeps the saved token on transient failure and permits a successful retry", async () => {
    api.read.mockRejectedValueOnce(new Error("Offline"));
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("your choice has been kept");
    expect(api.collection).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(await screen.findByRole("textbox", { name: "Specify relationship" })).toHaveValue("Cousin");
    expect(api.read).toHaveBeenCalledTimes(2);
  });

  it("deduplicates a pending read and aborts it when the form unmounts", async () => {
    let finish!: (value: QualifierSelectionState) => void;
    api.read.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    const view = render(<Harness />);
    const change = screen.getByRole("button", { name: "Change" });
    fireEvent.click(change); fireEvent.click(change);
    expect(api.read).toHaveBeenCalledTimes(1);
    const signal = api.read.mock.calls[0][2] as AbortSignal;
    expect(signal.aborted).toBe(false);
    view.unmount(); expect(signal.aborted).toBe(true);
    await act(async () => finish({ ...saved, status: "expired" }));
    expect(api.collection).not.toHaveBeenCalled();
  });

  it("does not present an expired saved choice as a valid selection", async () => {
    api.read.mockResolvedValue({ ...saved, status: "expired" });
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(await screen.findByRole("textbox", { name: "Specify relationship" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("no longer active");
    expect(api.collection).toHaveBeenCalledWith({ qualifier_selection_token: null });
  });
});
