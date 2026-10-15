import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import type { FreshDraft, FreshPayload } from "../api/fresh-draft.api";
import { preparePublicUploadFile } from "../services/public-upload-file";
import { FreshMemberForm } from "./fresh-member-form";

const api = vi.hoisted(() => ({ start: vi.fn(), read: vi.fn(), save: vi.fn(), upload: vi.fn(), complete: vi.fn(), document: vi.fn(), activity: vi.fn(), discard: vi.fn() }));
vi.mock("../api/fresh-draft.api", () => ({ freshDraftApi: () => api }));
vi.mock("../services/public-upload-file", async (original) => ({ ...await original<object>(), preparePublicUploadFile: vi.fn(async (file: File) => file) }));
const collection = { acquisition_mode: "file" as const, submission_mode: "single" as const };
const member = { sessionId: "private-member", submissionKey: "stable-final-key", completed: false };
const group = { name: "Synthetic trip", allow_files_from_device: true, custom_questions: [], custom_details: [], upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: false } } as unknown as UploadLinkResponse;
let server: FreshDraft;
const snapshot = () => structuredClone(server);
beforeEach(() => {
  vi.clearAllMocks();
  server = {
    id: "draft", revision: 1, expires_at: "2099-01-01", status: "active", verified_phone: null, collection,
    phone_verification_id: "verified-proof", phone_verification_expires_at: "2099-01-01",
    passport_fields: { given_names: "Person", surname: "Example", passport_number: "P1234567", nationality: "IND", place_of_issue: "DELHI", date_of_birth: "1990-01-01", date_of_issue: "2020-01-01", date_of_expiry: "2030-01-01", sex: "M" },
    current_details: { client_email: "person@example.test", client_phone: "+919999999999" }, custom_answers: {}, custom_detail_answers: {},
    documents: [{ id: "front", side: "front", state: "ready" }, { id: "back", side: "back", state: "ready" }], extracted_fields: {}, extraction_status: "succeeded",
  };
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private-test"), revokeObjectURL: vi.fn() }));
  api.start.mockImplementation(async () => snapshot()); api.read.mockImplementation(async () => snapshot());
  api.save.mockImplementation(async (payload: FreshPayload) => { server = { ...server, ...payload, revision: server.revision + 1 }; return snapshot(); });
  api.upload.mockImplementation(async () => { server = { ...server, revision: server.revision + 1, documents: [{ id: "replacement", side: "front", state: "ready" }, server.documents[1]] }; return snapshot(); });
  api.complete.mockImplementation(async () => { server.status = "submitted"; return { source_submission_id: "source", status: "submitted" }; });
  api.document.mockResolvedValue(new Blob(["saved"], { type: "image/jpeg" }));
  api.activity.mockResolvedValue({ images_present: true, presence_recorded: true, heartbeat_after_seconds: 60 });
  api.discard.mockResolvedValue(undefined);
});
async function setup() {
  const onBack = vi.fn(), onComplete = vi.fn();
  render(<FreshMemberForm token="trip" group={group} member={member} initial={collection} onStarted={vi.fn()} onComplete={onComplete} onBack={onBack} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Confirm details and submit" })).toBeEnabled());
  return { onBack, onComplete };
}

describe("fresh submission during image preparation", () => {
  it("blocks submit and Back through preparation and upload, then submits the new revision", async () => {
    let prepared!: (file: File) => void, uploaded!: () => void;
    vi.mocked(preparePublicUploadFile).mockReturnValueOnce(new Promise<File>((resolve) => { prepared = resolve; }));
    const transfer = new Promise<void>((resolve) => { uploaded = resolve; }), performUpload = api.upload.getMockImplementation()!;
    api.upload.mockImplementationOnce(async (...args) => { await transfer; return performUpload(...args); });
    const { onBack, onComplete } = await setup();
    const file = new File(["replacement"], "replacement.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [file] } });
    expect(screen.getByRole("button", { name: "Preparing your documents…" })).toBeDisabled();
    const back = screen.getByRole("button", { name: "Back" }); expect(back).toBeDisabled();
    fireEvent.click(back); fireEvent.submit(back.parentElement!.querySelector("form")!);
    expect(api.complete).not.toHaveBeenCalled(); expect(api.discard).not.toHaveBeenCalled(); expect(onBack).not.toHaveBeenCalled();
    await act(async () => { prepared(file); });
    await waitFor(() => expect(api.upload).toHaveBeenCalledOnce());
    expect(back).toBeDisabled(); expect(screen.getByRole("button", { name: "Preparing your documents…" })).toBeDisabled();
    await act(async () => { uploaded(); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Confirm details and submit" })).toBeEnabled());
    expect(back).toBeEnabled(); expect(api.complete).not.toHaveBeenCalled();
    fireEvent.submit(back.parentElement!.querySelector("form")!);
    await waitFor(() => expect(onComplete).toHaveBeenCalledOnce());
    expect(api.complete.mock.calls[0].slice(0, 3)).toEqual([2, "verified-proof", "stable-final-key"]);
  });

  it("restores navigation and submission when file preparation fails without changing the saved images", async () => {
    let reject!: (reason: Error) => void;
    vi.mocked(preparePublicUploadFile).mockReturnValueOnce(new Promise<File>((_, fail) => { reject = fail; }));
    const { onBack } = await setup();
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [new File(["invalid"], "invalid.jpg", { type: "image/jpeg" })] } });
    expect(screen.getByRole("button", { name: "Back" })).toBeDisabled();
    await act(async () => { reject(new Error("The image could not be prepared.")); });
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be prepared");
    expect(screen.getByRole("button", { name: "Confirm details and submit" })).toBeEnabled();
    expect(server.documents.map(({ id }) => id)).toEqual(["front", "back"]); expect(api.upload).not.toHaveBeenCalled(); expect(api.complete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() => expect(onBack).toHaveBeenCalledOnce()); expect(api.discard).toHaveBeenCalledOnce();
  });
});
