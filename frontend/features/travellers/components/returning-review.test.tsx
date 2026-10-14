import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { returningApi } from "../api/returning.api";
import { returningDraftApi, type ReturningDraft } from "../api/returning-draft.api";
import type { ReturningHistory } from "../types";
import { ReturningReview } from "./returning-review";
import { freshDraftApi } from "@/features/upload/api/fresh-draft.api";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";

vi.mock("../api/returning.api", () => ({ returningApi: { document: vi.fn(), history: vi.fn(), selectPassport: vi.fn(), requestContact: vi.fn(), verifyContact: vi.fn() } }));
vi.mock("../api/returning-draft.api", () => ({ returningDraftApi: { start: vi.fn(), read: vi.fn(), save: vi.fn(), upload: vi.fn(), document: vi.fn(), complete: vi.fn() } }));
vi.mock("@/features/upload/api/fresh-draft.api", () => ({ freshDraftApi: vi.fn() }));
vi.mock("@/features/upload/services/public-upload-file", async (original) => ({ ...await original<object>(), preparePublicUploadFile: vi.fn(async (file: File) => file) }));
vi.mock("next/dynamic", () => ({ default: () => ({ onCapture }: { onCapture: (file: File) => void }) => <button type="button" onClick={() => onCapture(new File(["camera"], "live.jpg", { type: "image/jpeg" }))}>Capture photo</button> }));
const qualifier = vi.fn();
const group = { name: "Test trip", require_selfie: true, allow_files_from_device: true, qualifier_relation_options: [{ code: "spouse", label: "Spouse" }], upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION } } as UploadLinkResponse;
const history: ReturningHistory = {
  display_name: "Test Person", contact_phone: "+919999999999",
  passport: { id: "passport-a", number: "A1234567", issuing_country: "IND", document_type: "P", date_of_birth: "1990-01-01", issue_date: "2020-01-01", expiry_date: "2030-01-01", revision: 2 },
  documents: [{ id: "front", label: "Front", content_type: "image/jpeg", available: true }, { id: "back", label: "Back", content_type: "image/jpeg", available: true }],
  suitability: { outcome: "review_required", reason_codes: ["DESTINATION_RULE_UNKNOWN"] },
  group_requirements: { custom_questions: [{ id: "meal", label: "Trip meal", enabled: true, required: true, options: ["Veg", "Jain"] }], custom_details: [], require_selfie: false, require_contact_phone: false, current_detail_fields: [{ key: "staff_code", label: "Staff code", required: true, options: [], type: "text" }] },
  missing_requirements: [], question_version: "v2", review_version: "review-v2", participation_revision: 3,
};
let state: ReturningDraft;
const accepted = { status: "accepted" as const, participation_id: "participation", source_submission_id: "saved-source" };
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear();
  qualifier.mockResolvedValue({ selection_token: "private-qualifier-token" });
  vi.mocked(freshDraftApi).mockReturnValue({ qualifier } as unknown as ReturnType<typeof freshDraftApi>);
  state = { id: "draft-a", revision: 1, expires_at: new Date(Date.now() + 86400000).toISOString(), status: "active", passport_fields: { surname: "Person", given_names: "Test", passport_number: "A1234567", date_of_birth: "1990-01-01", date_of_issue: "2020-01-01", date_of_expiry: "2030-01-01", nationality: "Indian", sex: "M", place_of_issue: "Test" }, current_details: { staff_code: "0009" }, custom_answers: { meal: "Veg" }, custom_detail_answers: {}, verified_phone: null, documents: [], extraction_status: "none", extracted_fields: {} };
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private-test"), revokeObjectURL: vi.fn() }));
  vi.stubGlobal("IntersectionObserver", class { constructor(private callback: IntersectionObserverCallback) {} observe() { queueMicrotask(() => this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)); } disconnect() {} });
  vi.mocked(returningApi.document).mockResolvedValue(new Blob(["synthetic"], { type: "image/jpeg" }));
  vi.mocked(returningDraftApi.document).mockResolvedValue(new Blob(["synthetic-new"], { type: "image/jpeg" }));
  vi.mocked(returningDraftApi.start).mockImplementation(async () => structuredClone(state));
  vi.mocked(returningDraftApi.read).mockImplementation(async () => structuredClone(state));
  vi.mocked(returningDraftApi.save).mockImplementation(async (payload) => { state = { ...state, ...structuredClone(payload), revision: state.revision + 1 }; return structuredClone(state); });
  vi.mocked(returningDraftApi.upload).mockImplementation(async (side) => {
    state = { ...state, revision: state.revision + 1, documents: [...state.documents.filter((document) => document.side !== side), { id: "new-" + side, side, state: "ready" }], extraction_status: side === "front" ? "succeeded" : state.extraction_status };
    return structuredClone(state);
  });
  vi.mocked(returningDraftApi.complete).mockResolvedValue(accepted);
});
async function setup(extra: Partial<Parameters<typeof ReturningReview>[0]> = {}) {
  const rendered = render(<ReturningReview history={history} groupName="Test trip" group={group} groupToken="test-token" onFresh={vi.fn()} onReplace={vi.fn()} {...extra} />);
  await screen.findByRole("button", { name: "Submit trip details" });
  return rendered;
}
function confirm() { fireEvent.click(screen.getByRole("checkbox", { name: /reviewed my passport/ })); }
function submit() { fireEvent.click(screen.getByRole("button", { name: "Submit trip details" })); }

describe("protected returning draft review", () => {
  it("resumes an already submitted receipt without reopening edit controls", async () => {
    state = { ...state, status: "submitted", result_status: "accepted", source_submission_id: "saved-source", participation_id: "participation" };
    render(<ReturningReview history={history} groupName="Test trip" groupToken="test-token" onFresh={vi.fn()} onReplace={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "Your trip details are saved" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Submit trip details" })).not.toBeInTheDocument();
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
  });
  it("shows protected images inline, removes client-only technical fields, and never submits on preview", async () => {
    const view = await setup();
    expect(await screen.findByRole("img", { name: "Passport details page" })).toBeVisible();
    expect(await screen.findByRole("img", { name: "Passport address page" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /Open preview/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Issuing country")).not.toBeInTheDocument();
    expect(screen.queryByText("Document Type")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Current WhatsApp contact" })).toBeVisible();
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeEnabled();
    view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalled();
  });
  it("autosaves edits only to the draft and stores no personal values in resume metadata", async () => {
    await setup();
    fireEvent.change(screen.getByLabelText(/Staff code/), { target: { value: "private-staff-729" } });
    await waitFor(() => expect(returningDraftApi.save).toHaveBeenCalled());
    expect(state.current_details.staff_code).toBe("private-staff-729");
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
    const metadata = JSON.stringify(localStorage);
    expect(metadata).not.toContain("private-staff-729"); expect(metadata).not.toContain("A1234567"); expect(metadata).not.toContain("Test Person");
  });
  it("submits current revision only on explicit confirmation and reuses its final operation on a retry", async () => {
    vi.mocked(returningDraftApi.complete).mockRejectedValueOnce(new Error("Temporary failure")).mockResolvedValueOnce(accepted);
    await setup();
    fireEvent.change(screen.getByRole("combobox", { name: /Trip meal/ }), { target: { value: "Jain" } });
    confirm(); submit(); await screen.findByRole("alert");
    submit(); await screen.findByRole("heading", { name: "Your trip details are saved" });
    const calls = vi.mocked(returningDraftApi.complete).mock.calls;
    expect(calls[0][0]).toEqual(calls[1][0]);
    expect(calls[0][0]).toMatchObject({ expected_revision: 2, review_version: "review-v2", question_version: "v2", expected_participation_revision: 3, information_confirmed: true });
    expect(state.custom_answers.meal).toBe("Jain");
    expect(localStorage.length).toBe(0);
  });
  it("binds a family source and refuses a receipt without a saved submission", async () => {
    const onCompleted = vi.fn();
    const ownedSource = { source_submission_id: "family-member", expected_extraction_revision: 3, uploadSessionId: "member-capability" };
    vi.mocked(returningDraftApi.complete).mockResolvedValueOnce({ status: "submitted", participation_id: "participation" }).mockResolvedValueOnce(accepted);
    await setup({ ownedSource, onCompleted });
    confirm(); submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be linked");
    expect(onCompleted).not.toHaveBeenCalled();
    expect(returningDraftApi.complete).toHaveBeenLastCalledWith(expect.objectContaining({ owned_source: { source_submission_id: "family-member", expected_extraction_revision: 3 } }), "draft-a", expect.any(AbortSignal), "member-capability");
    submit(); await screen.findByRole("heading", { name: "Your trip details are saved" });
    expect(onCompleted).toHaveBeenCalledExactlyOnceWith(accepted);
  });
  it("requires the new back page after front replacement but does not create an official source early", async () => {
    await setup();
    fireEvent.click(screen.getByRole("button", { name: "Upload updated passport" }));
    expect(screen.getByLabelText("Upload address details page")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [new File(["front"], "front.jpg", { type: "image/jpeg" })] } });
    await screen.findByText(/Add the address page/);
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Upload address details page"), { target: { files: [new File(["back"], "back.jpg", { type: "image/jpeg" })] } });
    await waitFor(() => expect(screen.queryByText(/Add the address page/)).not.toBeInTheDocument());
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
    confirm(); submit(); await screen.findByRole("heading", { name: "Your trip details are saved" });
    expect(returningDraftApi.upload).toHaveBeenCalledTimes(2);
  });
  it("exposes missing required pages and blocks unavailable or failed passport checks", async () => {
    state.extraction_status = "failed";
    await setup({ history: { ...history, missing_requirements: ["passport_back"] } });
    expect(screen.getByLabelText("Upload address details page")).toBeEnabled();
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("couldn’t read this page");
  });
  it("completes a required live photo without reuploading saved passport pages", async () => {
    await setup({ group: { ...group, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, visa_photo_upload: false } }, history: { ...history, missing_requirements: ["fresh_photo"] } });
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
    expect(screen.queryByLabelText("Upload traveller photo")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Upload personal details page")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use camera" }));
    fireEvent.click(await screen.findByRole("button", { name: "Capture photo" }));
    await screen.findByRole("img", { name: "Traveller photo" });
    expect(state.collection?.visa_photo_source).toBe("camera");
    expect(screen.getByRole("img", { name: "Passport details page" })).toBeVisible();
    expect(screen.getByRole("img", { name: "Passport address page" })).toBeVisible();
    expect(returningDraftApi.upload).toHaveBeenCalledExactlyOnceWith("photo", expect.any(File), 2, expect.any(String), "draft-a", expect.any(AbortSignal));
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
    confirm(); submit(); await screen.findByRole("heading", { name: "Your trip details are saved" });
  });
  it("requires a saved relationship token and configured photo before final submission", async () => {
    await setup({ group, history: { ...history, missing_requirements: ["qualifier_relationship", "visa_photo"] } });
    fireEvent.change(screen.getByLabelText("Upload traveller photo"), { target: { files: [new File(["photo"], "photo.jpg", { type: "image/jpeg" })] } });
    await screen.findByRole("img", { name: "Traveller photo" });
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox", { name: "Passenger's relationship" }), { target: { value: "spouse" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Qualifier relationship saved");
    await waitFor(() => expect(state.collection?.qualifier_selection_token).toBe("private-qualifier-token"));
    expect(qualifier).toHaveBeenCalledOnce();
    expect(state.collection?.visa_photo_source).toBe("file");
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
    confirm(); submit(); await screen.findByRole("heading", { name: "Your trip details are saved" });
    expect(returningDraftApi.upload).toHaveBeenCalledOnce();
  });
  it("does not guess capture permissions when current group settings are unavailable", async () => {
    await setup({ group: undefined, history: { ...history, missing_requirements: ["fresh_photo"] } });
    expect(screen.getByRole("alert")).toHaveTextContent("document settings could not be loaded");
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
    expect(screen.queryByLabelText("Upload traveller photo")).not.toBeInTheDocument();
  });
  it("captures replacement passport pages in order on a camera-only trip", async () => {
    await setup({ group: { ...group, allow_files_from_device: false } });
    fireEvent.click(screen.getByRole("button", { name: "Upload updated passport" }));
    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(0);
    const cameras = screen.getAllByRole("button", { name: "Use camera" });
    expect(cameras[1]).toBeDisabled(); fireEvent.click(cameras[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Capture photo" }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Use camera" })[1]).toBeEnabled());
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
    fireEvent.click(screen.getAllByRole("button", { name: "Use camera" })[1]);
    fireEvent.click(await screen.findByRole("button", { name: "Capture photo" }));
    await waitFor(() => expect(state.documents).toHaveLength(2));
    expect(state.collection?.acquisition_mode).toBe("camera");
    expect(vi.mocked(returningDraftApi.upload).mock.calls.map(([side]) => side)).toEqual(["front", "back"]);
    confirm(); submit(); await screen.findByRole("heading", { name: "Your trip details are saved" });
  });
  it("allows a front-only configured replacement without requesting an unconfigured back page", async () => {
    await setup({ group: { ...group, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: false, passport_upload_pages: ["front"] } } });
    fireEvent.click(screen.getByRole("button", { name: "Upload updated passport" }));
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [new File(["front"], "front.jpg", { type: "image/jpeg" })] } });
    await waitFor(() => expect(state.documents).toHaveLength(1));
    expect(screen.queryByLabelText("Upload address details page")).not.toBeInTheDocument();
    expect(screen.queryByText(/Add the address page/)).not.toBeInTheDocument();
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeEnabled();
    submit(); await screen.findByRole("heading", { name: "Your trip details are saved" });
  });
  it("refreshes changed requirements and resets the final confirmation", async () => {
    vi.mocked(returningDraftApi.complete).mockRejectedValueOnce({ status: 409, message: "Trip requirements changed." });
    vi.mocked(returningApi.history).mockResolvedValue({ ...history, review_version: "review-v3", question_version: "v3", group_requirements: { ...history.group_requirements, custom_questions: [...history.group_requirements.custom_questions, { id: "seat", label: "Seat preference", enabled: true, required: true, options: ["Window", "Aisle"] }] } });
    await setup(); confirm(); submit(); await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Refresh current trip requirements" }));
    await screen.findByRole("combobox", { name: /Seat preference/ });
    expect(screen.getByRole("combobox", { name: /Trip meal/ })).toHaveValue("Veg");
    expect(screen.getByRole("checkbox", { name: /reviewed my passport/ })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
  });
  it("stages a verified contact, retains other draft answers and resets confirmation", async () => {
    vi.mocked(returningApi.requestContact).mockResolvedValue({ expires_in_seconds: 300, resend_after_seconds: 30 });
    vi.mocked(returningApi.verifyContact).mockImplementation(async () => { state = { ...state, revision: state.revision + 1, verified_phone: "+919888888888" }; return { stage: "review" }; });
    await setup({ history: { ...history, contact_phone: null, group_requirements: { ...history.group_requirements, require_contact_phone: true } } });
    confirm(); expect(screen.getByRole("button", { name: "Submit trip details" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Add WhatsApp number" }));
    fireEvent.change(await screen.findByLabelText("New WhatsApp number", { exact: false }), { target: { value: "9888888888" } });
    fireEvent.click(screen.getByRole("button", { name: "Send WhatsApp code" }));
    fireEvent.change(await screen.findByLabelText("WhatsApp verification code", { exact: false }), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Use this verified number/ }));
    fireEvent.click(screen.getByRole("button", { name: "Verify for this draft" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(await screen.findByText("+919888888888")).toBeVisible();
    expect(screen.getByText(/Your contact updates when you submit/)).toBeVisible();
    expect(screen.getByRole("checkbox", { name: /reviewed my passport/ })).not.toBeChecked();
    expect(returningDraftApi.complete).not.toHaveBeenCalled();
    expect(returningApi.history).not.toHaveBeenCalled();
  });
});
