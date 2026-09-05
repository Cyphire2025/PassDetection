import { useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_UPLOAD_CONFIGURATION, type UploadConfiguration } from "@/features/passports/types/upload-configuration";
import { emptyDocumentBundle } from "../services/upload-flow-helpers";
import { PassportUploadPage } from "./passport-upload-page";
import { VisaSelfieChoice } from "./upload-flow-passport-picker";
import { ConfiguredClientFields, CustomDetailFields, CustomQuestionFields, DepartureCitySelect } from "./upload-flow-fields";
import { ProtectedUploadDocumentImage } from "./protected-upload-document-image";
import { uploadApi } from "../api/upload.api";

vi.mock("../api/upload.api", () => ({ uploadApi: { getUploadDocument: vi.fn() } }));

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:passport-preview"), revokeObjectURL: vi.fn() }));
});
afterEach(() => vi.restoreAllMocks());

function UploadHarness({ config, onContinue }: { config: UploadConfiguration; onContinue: () => void }) {
  const [bundle, setBundle] = useState(emptyDocumentBundle);
  return <PassportUploadPage bundle={bundle} config={config} onChange={setBundle} onContinue={onContinue} onBack={() => {}} error={null} />;
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
    fireEvent.change(input, { target: { files: [new File([new Uint8Array(2 * 1024 * 1024 + 1)], "large.jpg", { type: "image/jpeg" })] } });
    expect(screen.getByRole("alert")).toHaveTextContent("2 MB or smaller");
    expect(screen.getByText("small.jpg")).toBeInTheDocument();
    expect(screen.queryByText("large.jpg")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Address Details/ })).not.toBeInTheDocument();
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
