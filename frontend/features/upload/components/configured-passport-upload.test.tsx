import { useState } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_UPLOAD_CONFIGURATION, type UploadConfiguration } from "@/features/passports/types/upload-configuration";
import { emptyDocumentBundle } from "../services/upload-flow-helpers";
import { PassportUploadPage } from "./passport-upload-page";
import { VisaSelfieChoice } from "./upload-flow-passport-picker";
import { ConfiguredClientFields, CustomDetailFields, CustomQuestionFields, DepartureCitySelect } from "./upload-flow-fields";
import { ProtectedUploadDocumentImage } from "./protected-upload-document-image";
import { uploadApi } from "../api/upload.api";
import { preparePublicUploadFile } from "../services/public-upload-file";
import type { PassportDocumentBundle } from "./upload-flow.types";

vi.mock("../services/public-upload-file", async (importOriginal) => ({
  ...await importOriginal<typeof import("../services/public-upload-file")>(),
  preparePublicUploadFile: vi.fn(),
}));

vi.mock("../api/upload.api", () => ({ uploadApi: { getUploadDocument: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(preparePublicUploadFile).mockImplementation(async (file) => new File(["prepared JPEG"], `${file.name}.jpg`, { type: "image/jpeg" }));
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:passport-preview"), revokeObjectURL: vi.fn() }));
});
afterEach(() => vi.restoreAllMocks());

function UploadHarness({ config, onContinue }: { config: UploadConfiguration; onContinue: (bundle: PassportDocumentBundle) => void }) {
  const [bundle, setBundle] = useState(emptyDocumentBundle);
  return <PassportUploadPage token="public-link" uploadSessionId="private-session" bundle={bundle} config={config} onChange={setBundle} onContinue={() => onContinue(bundle)} onBack={() => {}} error={null} />;
}

describe("configured passport page upload", () => {
  it("orders only selected pages, previews chosen files and requires each selected page", async () => {
    const onContinue = vi.fn();
    const config = { ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["back", "cover", "front", "back_cover"] as UploadConfiguration["passport_upload_pages"] };
    render(<UploadHarness config={config} onContinue={onContinue} />);
    expect(screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual([
      "1. Passport Front Cover", "2. Passport Back Cover", "3. Personal Details Page", "4. Address Details Page",
    ]);
    expect(screen.getByRole("button", { name: "Save passport pages and continue" })).toBeDisabled();
    for (const label of ["Passport Front Cover", "Passport Back Cover", "Personal Details Page", "Address Details Page"]) {
      fireEvent.change(screen.getByLabelText(`Upload ${label}`), { target: { files: [new File(["image"], `${label}.jpg`, { type: "image/jpeg" })] } });
    }
    await waitFor(() => expect(screen.getByRole("img", { name: "Selected Personal Details Page" })).toHaveAttribute("src", "blob:passport-preview"));
    await userEvent.click(screen.getByRole("button", { name: "Save passport pages and continue" }));
    expect(onContinue).toHaveBeenCalledOnce();
    await userEvent.click(screen.getByRole("button", { name: "Remove passport front cover" }));
    expect(screen.getByRole("button", { name: "Save passport pages and continue" })).toBeDisabled();
  });

  it("rejects files larger than 2 MB without replacing a previously selected valid image", async () => {
    render(<UploadHarness config={{ ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front"] }} onContinue={() => {}} />);
    const input = screen.getByLabelText("Upload Personal Details Page");
    fireEvent.change(input, { target: { files: [new File(["valid"], "small.jpg", { type: "image/jpeg" })] } });
    await screen.findByText("small.jpg");
    fireEvent.change(input, { target: { files: [new File([new Uint8Array(2 * 1024 * 1024 + 1)], "large.jpg", { type: "image/jpeg" })] } });
    expect(screen.getByRole("alert")).toHaveTextContent("2 MB or smaller");
    expect(screen.getByText("small.jpg")).toBeInTheDocument();
    expect(screen.queryByText("large.jpg")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Address Details/ })).not.toBeInTheDocument();
  });


  it.each(["pdf", "heic"])("prepares %s as a JPEG preview in the same upload box and retains the original for submission", async (extension) => {
    const original = new File(["original"], `passport.${extension}`, { type: extension === "pdf" ? "application/pdf" : "image/heic" });
    const prepared = new File(["JPEG render"], "preview.jpg", { type: "image/jpeg" });
    vi.mocked(preparePublicUploadFile).mockResolvedValueOnce(prepared);
    const onContinue = vi.fn();
    render(<UploadHarness config={{ ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front"] }} onContinue={onContinue} />);
    const uploadBox = screen.getByRole("group", { name: "Personal Details Page upload" });
    fireEvent.change(within(uploadBox).getByLabelText("Upload Personal Details Page"), { target: { files: [original] } });
    expect(within(uploadBox).getByRole("status")).toHaveTextContent("Checking file and preparing preview");
    expect(screen.getByRole("button", { name: "Save passport pages and continue" })).toBeDisabled();
    await within(uploadBox).findByRole("img", { name: "Selected Personal Details Page" });
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledWith(prepared));
    expect(preparePublicUploadFile).toHaveBeenCalledWith(original, expect.objectContaining({ token: "public-link", uploadSessionId: "private-session", purpose: "passport", signal: expect.any(AbortSignal) }));
    expect(within(uploadBox).getByText(original.name)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save passport pages and continue" }));
    expect(onContinue.mock.calls[0][0].front).toBe(original);
  });

  it.each(["webp", "bmp", "tiff"])("rejects removed %s formats before any preparation request", (extension) => {
    render(<UploadHarness config={{ ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front"] }} onContinue={() => {}} />);
    const input = screen.getByLabelText("Upload Personal Details Page");
    expect(input.getAttribute("accept")).not.toContain(`.${extension}`);
    fireEvent.change(input, { target: { files: [new File(["removed"], `page.${extension}`, { type: `image/${extension}` })] } });
    expect(screen.getByRole("alert")).toHaveTextContent("single-page PDF");
    expect(preparePublicUploadFile).not.toHaveBeenCalled();
  });

  it("preserves a valid selection when the server rejects a replacement PDF and displays its page-count error", async () => {
    const onContinue = vi.fn();
    const original = new File(["original"], "small.png", { type: "image/png" });
    render(<UploadHarness config={{ ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front"] }} onContinue={onContinue} />);
    const input = screen.getByLabelText("Upload Personal Details Page");
    fireEvent.change(input, { target: { files: [original] } });
    await screen.findByRole("img", { name: "Selected Personal Details Page" });
    const pending = deferred<File>();
    vi.mocked(preparePublicUploadFile).mockReturnValueOnce(pending.promise);
    fireEvent.change(input, { target: { files: [new File(["two pages"], "multiple.pdf", { type: "application/pdf" })] } });
    expect(screen.getByRole("button", { name: "Save passport pages and continue" })).toBeDisabled();
    await act(async () => { pending.reject({ code: "INVALID_PDF", message: "PDFs must contain exactly one page." }); });
    expect(screen.getByRole("alert")).toHaveTextContent("PDFs must contain exactly one page.");
    expect(screen.getByText("small.png")).toBeInTheDocument();
    expect(screen.queryByText("multiple.pdf")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save passport pages and continue" }));
    expect(onContinue.mock.calls[0][0].front).toBe(original);
  });

  it("merges independent page preparations even when they finish out of order", async () => {
    const frontPending = deferred<File>(); const backPending = deferred<File>();
    vi.mocked(preparePublicUploadFile).mockReturnValueOnce(frontPending.promise).mockReturnValueOnce(backPending.promise);
    const front = new File(["front"], "front.pdf", { type: "application/pdf" });
    const back = new File(["back"], "back.png", { type: "image/png" });
    const onContinue = vi.fn();
    render(<UploadHarness config={{ ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front", "back"] }} onContinue={onContinue} />);
    fireEvent.change(screen.getByLabelText("Upload Personal Details Page"), { target: { files: [front] } });
    fireEvent.change(screen.getByLabelText("Upload Address Details Page"), { target: { files: [back] } });
    await act(async () => { backPending.resolve(new File(["back JPEG"], "back.jpg", { type: "image/jpeg" })); });
    expect(screen.getByRole("button", { name: "Save passport pages and continue" })).toBeDisabled();
    await act(async () => { frontPending.resolve(new File(["front JPEG"], "front.jpg", { type: "image/jpeg" })); });
    await userEvent.click(screen.getByRole("button", { name: "Save passport pages and continue" }));
    expect(onContinue.mock.calls[0][0]).toMatchObject({ front, back });
  });

  it("ignores an obsolete preparation when the user selects a newer file", async () => {
    const first = deferred<File>(); const second = deferred<File>();
    vi.mocked(preparePublicUploadFile).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const firstFile = new File(["old"], "old.pdf", { type: "application/pdf" });
    const secondFile = new File(["new"], "new.png", { type: "image/png" });
    const onContinue = vi.fn();
    render(<UploadHarness config={{ ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front"] }} onContinue={onContinue} />);
    const input = screen.getByLabelText("Upload Personal Details Page");
    fireEvent.change(input, { target: { files: [firstFile] } });
    fireEvent.change(input, { target: { files: [secondFile] } });
    expect(vi.mocked(preparePublicUploadFile).mock.calls[0][1].signal?.aborted).toBe(true);
    await act(async () => { second.resolve(new File(["new JPEG"], "new.jpg", { type: "image/jpeg" })); });
    await act(async () => { first.resolve(new File(["old JPEG"], "old.jpg", { type: "image/jpeg" })); });
    expect(screen.getByText("new.png")).toBeInTheDocument();
    expect(screen.queryByText("old.pdf")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save passport pages and continue" }));
    expect(onContinue.mock.calls[0][0].front).toBe(secondFile);
  });

  it("cancels removal and unmount requests so late results cannot restore selected files", async () => {
    const first = deferred<File>(); const second = deferred<File>();
    vi.mocked(preparePublicUploadFile).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const view = render(<UploadHarness config={{ ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front"] }} onContinue={() => {}} />);
    const input = screen.getByLabelText("Upload Personal Details Page");
    fireEvent.change(input, { target: { files: [new File(["first"], "first.pdf", { type: "application/pdf" })] } });
    await userEvent.click(screen.getByRole("button", { name: "Remove personal details page" }));
    expect(vi.mocked(preparePublicUploadFile).mock.calls[0][1].signal?.aborted).toBe(true);
    await act(async () => { first.resolve(new File(["prepared"], "first.jpg", { type: "image/jpeg" })); });
    expect(screen.queryByRole("img", { name: "Selected Personal Details Page" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save passport pages and continue" })).toBeDisabled();
    fireEvent.change(input, { target: { files: [new File(["second"], "second.pdf", { type: "application/pdf" })] } });
    view.unmount();
    expect(vi.mocked(preparePublicUploadFile).mock.calls[1][1].signal?.aborted).toBe(true);
    await act(async () => { second.resolve(new File(["prepared"], "second.jpg", { type: "image/jpeg" })); });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it.each(["context", "bundle"])("cancels stale work when the %s is reset", async (resetKind) => {
    const pending = deferred<File>();
    vi.mocked(preparePublicUploadFile).mockReturnValueOnce(pending.promise);
    const onChange = vi.fn();
    const config = { ...DEFAULT_UPLOAD_CONFIGURATION, passport_upload_pages: ["front"] as UploadConfiguration["passport_upload_pages"] };
    const bundle = emptyDocumentBundle();
    const props = { token: "first-link", uploadSessionId: "session", bundle, config, onChange, onContinue: () => {}, onBack: () => {}, error: null };
    const view = render(<PassportUploadPage {...props} />);
    fireEvent.change(screen.getByLabelText("Upload Personal Details Page"), { target: { files: [new File(["pending"], "pending.pdf", { type: "application/pdf" })] } });
    expect(screen.getByRole("status")).toBeInTheDocument();
    view.rerender(<PassportUploadPage {...props} token={resetKind === "context" ? "other-link" : props.token} bundle={resetKind === "bundle" ? emptyDocumentBundle() : bundle} />);
    expect(vi.mocked(preparePublicUploadFile).mock.calls[0][1].signal?.aborted).toBe(true);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await act(async () => { pending.resolve(new File(["rendered"], "preview.jpg", { type: "image/jpeg" })); });
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("img", { name: "Selected Personal Details Page" })).not.toBeInTheDocument();
  });

  it("shows only enabled Visa Photo methods and marks an optional photo correctly", () => {
    render(<VisaSelfieChoice file={null} allowCamera={false} allowUpload required={false} onCameraClick={() => {}} onUploadClick={() => {}} />);
    expect(screen.queryByRole("button", { name: "Use live camera" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload studio photo" })).toBeInTheDocument();
    expect(screen.getByText("Optional", { exact: true })).toBeInTheDocument();
  });

  it("uses edited field labels, accepts alphanumeric codes and enforces each required setting independently", () => {
    render(<form><ConfiguredClientFields config={{ ...DEFAULT_UPLOAD_CONFIGURATION, agent_employee_code_label: "Producer Code", agency_dealership_name_label: "Branch Name", required_fields: { staff_code: true, agent_employee_code: false, agency_dealership_name: false } }} baseCityEnabled={false} askNearestDomesticAirport={false} staffCodeEnabled agentEmployeeCodeEnabled designationEnabled={false} agencyDealershipNameEnabled mealPreferenceEnabled={false} baseCity="" nearestDomesticAirport="" staffCode="" agentEmployeeType="" agentEmployeeCode="A-42" designation="" agencyDealershipName="" mealPreference="" onBaseCity={() => {}} onNearestDomesticAirport={() => {}} onStaffCode={() => {}} onAgentEmployeeType={() => {}} onAgentEmployeeCode={() => {}} onDesignation={() => {}} onAgencyDealershipName={() => {}} onMealPreference={() => {}} />
      <CustomQuestionFields questions={[{ id: "q1", label: "Required question", enabled: true, required: true, options: ["Yes"] }, { id: "q2", label: "Optional question", enabled: true, required: false, options: ["Yes"] }]} answers={{}} onChange={() => {}} />
      <CustomDetailFields details={[{ id: "d1", label: "Optional detail", enabled: true, required: false }]} answers={{}} onChange={() => {}} />
      <DepartureCitySelect value="" cities={["Delhi"]} onChange={() => {}} required={false} />
    </form>);
    expect(screen.queryByLabelText("Agent or Employee")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Producer Code")).toHaveValue("A-42");
    expect(screen.getByLabelText("Producer Code")).not.toBeRequired();
    expect(screen.getByLabelText("Branch Name")).not.toBeRequired();
    expect(screen.getByLabelText("Staff Code")).toBeRequired();
    expect(screen.getByLabelText("Required question *")).toBeRequired();
    expect(screen.getByLabelText("Optional question (optional)")).not.toBeRequired();
    expect(screen.getByLabelText("Optional detail")).not.toBeRequired();
    expect(screen.getByLabelText("Nearest International Airport")).not.toBeRequired();
  });

  it("keeps authenticated image retrieval and uses bounded orientation-specific preview dimensions", async () => {
    vi.mocked(uploadApi.getUploadDocument).mockResolvedValue(new Blob(["image"], { type: "image/jpeg" }));
    render(<ProtectedUploadDocumentImage token="group-token" submissionId="submission-1" uploadSessionId="private-session" documentType="cover" alt="Saved cover" />);
    const preview = await screen.findByRole("img", { name: "Saved cover" });
    expect(uploadApi.getUploadDocument).toHaveBeenCalledWith("group-token", "submission-1", "cover", "private-session", expect.any(AbortSignal));
    Object.defineProperties(preview, { naturalWidth: { value: 800, configurable: true }, naturalHeight: { value: 1200, configurable: true } });
    fireEvent.load(preview);
    expect(screen.getByTestId("secure-document-preview-frame")).toHaveStyle({ width: "220px", height: "300px" });
    expect(preview).toHaveStyle({ objectFit: "contain", maxHeight: "300px" });
    Object.defineProperties(preview, { naturalWidth: { value: 1200 }, naturalHeight: { value: 800 } });
    fireEvent.load(preview);
    expect(screen.getByTestId("secure-document-preview-frame")).toHaveStyle({ width: "360px", height: "230px" });
  });

  it("offers a credentialed retry when a saved image cannot be decoded", async () => {
    vi.mocked(uploadApi.getUploadDocument).mockResolvedValue(new Blob(["image"], { type: "image/jpeg" }));
    render(<ProtectedUploadDocumentImage token="group-token" submissionId="submission-1" uploadSessionId="private-session" documentType="front" alt="Saved front" overlay={<span data-testid="field-overlay" />} />);
    const preview = await screen.findByRole("img", { name: "Saved front" });
    expect(screen.getByTestId("field-overlay").parentElement).toBe(preview.parentElement);
    fireEvent.error(preview);
    expect(screen.getByRole("alert")).toHaveTextContent("Secure preview is unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Retry preview" }));
    await screen.findByRole("img", { name: "Saved front" });
    expect(uploadApi.getUploadDocument).toHaveBeenLastCalledWith("group-token", "submission-1", "front", "private-session", expect.any(AbortSignal));
  });
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
