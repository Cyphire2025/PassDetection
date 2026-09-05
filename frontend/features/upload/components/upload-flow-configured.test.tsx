import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import { UploadFlow } from "./upload-flow";

const mocks = vi.hoisted(() => ({
  group: {} as Record<string, unknown>,
  upload: vi.fn(), submit: vi.fn(), getStatus: vi.fn(), report: vi.fn(), reportOnce: vi.fn(),
}));
vi.mock("@/features/passports/hooks/use-upload-links", () => ({ useUploadLinkByToken: () => ({ data: mocks.group, isLoading: false, error: null }) }));
vi.mock("../hooks/use-upload", () => ({ useUploadPassport: () => ({ mutateAsync: mocks.upload }), useSubmitClientPassportReview: () => ({ mutateAsync: mocks.submit }) }));
vi.mock("../hooks/use-public-flow-telemetry", () => ({ usePublicFlowTelemetry: () => ({ report: mocks.report, reportPublicFlowOnce: mocks.reportOnce }) }));
vi.mock("../api/upload.api", () => ({ uploadApi: { getUploadStatus: mocks.getStatus } }));
vi.mock("./protected-upload-document-image", () => ({ ProtectedUploadDocumentImage: ({ alt }: { alt: string }) => <span>{alt}</span> }));
vi.mock("../services/upload-flow-bootstrap", () => ({ runUploadFlowBootstrap: async ({ actions }: { actions: { setStep: (value: string) => void } }) => { await Promise.resolve(); actions.setStep("MODE_SELECT"); } }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:selected-passport"), revokeObjectURL: vi.fn() }));
  window.sessionStorage.clear();
  mocks.group = { id: "group-1", name: "Test Travel Group", token: "test-token", require_selfie: false, allow_files_from_device: true,
    base_city_enabled: true, agent_employee_code_enabled: true, nearest_international_airport_enabled: true, departure_cities: ["Delhi"],
    custom_questions: [{ id: "optional-question", label: "Optional activity", enabled: true, required: false, options: ["Walking"] }],
    custom_details: [{ id: "optional-detail", label: "Optional reference", enabled: true, required: false }],
    upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_enabled: false, passport_required: false, required_fields: { base_city: false, agent_employee_code: false, departure_city: false }, agent_employee_code_label: "Producer Code" },
  };
  mocks.upload.mockImplementation(async ({ client_name }: { client_name: string }) => ({ id: `saved-${client_name}`, client_name, image_s3_key: "", status: "ready_for_client_review", extraction_status: "ready_for_review", extracted_fields: null }));
  mocks.submit.mockResolvedValue({ status: "submitted" });
});

describe("public configurable upload flow", () => {
  it("shows the saved travel dates without changing their calendar day", async () => {
    vi.stubEnv("TZ", "America/Los_Angeles");
    mocks.group.travel_date = "2026-01-01";
    mocks.group.return_date = "2026-01-09";
    try {
      render(<UploadFlow token="test-token" />);
      await screen.findByRole("button", { name: /Single/ });
      expect(screen.getByText("Test Travel Group")).toBeInTheDocument();
      expect(screen.getByText("Departure Date")).toBeInTheDocument();
      expect(screen.getByText("Return Date")).toBeInTheDocument();
      expect(screen.getByText("1 Jan 2026")).toHaveAttribute("datetime", "2026-01-01");
      expect(screen.getByText("9 Jan 2026")).toHaveAttribute("datetime", "2026-01-09");
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("keeps legacy links readable when travel dates are unavailable", async () => {
    mocks.group.travel_date = null;
    mocks.group.return_date = "2026-02-30";
    render(<UploadFlow token="test-token" />);
    await screen.findByRole("button", { name: /Single/ });
    expect(screen.getByText("Test Travel Group")).toBeInTheDocument();
    expect(screen.queryByText("Departure Date")).not.toBeInTheDocument();
    expect(screen.queryByText("Return Date")).not.toBeInTheDocument();
    expect(screen.queryByText("Invalid Date")).not.toBeInTheDocument();
  });

  it("creates a durable document-free submission, skips OCR and allows optional configured details to stay blank", async () => {
    render(<UploadFlow token="test-token" />);
    await userEvent.click(await screen.findByRole("button", { name: /Single/ }));
    expect(screen.queryByRole("button", { name: "Live scan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload passport images" })).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Full name/), "Asha Example");
    await userEvent.click(screen.getByRole("button", { name: "Continue to your details" }));
    await screen.findByRole("heading", { name: "Review Traveller Details" });
    expect(mocks.upload).toHaveBeenCalledWith(expect.objectContaining({ file: null, passportBackFile: null, client_name: "Asha Example", uploadIdempotencyKey: expect.any(String) }));
    expect(mocks.getStatus).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Passport Number")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Producer Code")).not.toBeRequired();
    await userEvent.type(screen.getByLabelText("Email"), "asha@example.com");
    await userEvent.type(screen.getByLabelText("WhatsApp active number"), "9999999999");
    await userEvent.click(screen.getByRole("button", { name: "Submit Traveller Details" }));
    await screen.findByRole("heading", { name: "Details Submitted" });
    expect(mocks.submit).toHaveBeenCalledWith(expect.objectContaining({ submissionId: "saved-Asha Example", confirmed_fields: { given_names: "Asha Example" }, custom_answers: [], custom_detail_answers: [], agent_employee_type: null }));
  });

  it("requires a name before creating a document-free record", async () => {
    render(<UploadFlow token="test-token" />);
    await userEvent.click(await screen.findByRole("button", { name: /Single/ }));
    await userEvent.click(screen.getByRole("button", { name: "Continue to your details" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter the passenger name");
    expect(mocks.upload).not.toHaveBeenCalled();
  });

  it("keeps a stored passport with missing verification blocked even when passport collection is optional", async () => {
    mocks.upload.mockResolvedValue({ id: "unverified", client_name: "Asha Example", image_s3_key: "stored-front.jpg", status: "ready_for_client_review", extraction_status: "ready_for_review", extracted_fields: null });
    render(<UploadFlow token="test-token" />);
    await userEvent.click(await screen.findByRole("button", { name: /Single/ }));
    await userEvent.type(screen.getByLabelText(/Full name/), "Asha Example");
    await userEvent.click(screen.getByRole("button", { name: "Continue to your details" }));
    await screen.findByRole("heading", { name: "Passport Verification Required" });
    expect(screen.queryByRole("button", { name: "Submit Traveller Details" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry verification on saved image" })).toBeInTheDocument();
  });

  it("hides disabled camera methods and opens the requested passport upload page", async () => {
    mocks.group.require_selfie = true;
    mocks.group.upload_configuration = { ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: false, visa_photo_live_capture: false, visa_photo_required: false, passport_upload_pages: ["cover", "back_cover", "front", "back"] };
    render(<UploadFlow token="test-token" />);
    await userEvent.click(await screen.findByRole("button", { name: /Single/ }));
    expect(screen.queryByRole("button", { name: "Live scan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use live camera" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload studio photo" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Upload passport images" }));
    expect(screen.getAllByRole("heading", { level: 2 })).toHaveLength(4);
    expect(screen.getByLabelText("Upload Passport Front Cover")).toBeInTheDocument();
  });

  it("supports document-free family members with a durable record and required head contact for each family submission", async () => {
    render(<UploadFlow token="test-token" />);
    await userEvent.click(await screen.findByRole("button", { name: /Family/ }));
    const names = screen.getAllByPlaceholderText("Full name");
    await userEvent.type(names[0], "Asha Example");
    await userEvent.type(names[1], "Rahul Example");
    const genders = screen.getAllByLabelText("Gender");
    await userEvent.selectOptions(genders[0], "Female");
    await userEvent.selectOptions(genders[1], "Male");
    await userEvent.selectOptions(screen.getAllByLabelText("Relation")[1], "Spouse");
    await userEvent.click(screen.getByRole("button", { name: "Continue to Documents" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue to your details" }));
    await waitFor(() => expect(mocks.upload).toHaveBeenCalledTimes(1));
    await userEvent.click(await screen.findByRole("button", { name: "Continue to your details" }));
    await screen.findByRole("heading", { name: "Review Family Details" });
    expect(mocks.upload).toHaveBeenCalledTimes(2);
    await userEvent.type(screen.getByLabelText("Head email"), "asha@example.com");
    await userEvent.type(screen.getByLabelText("Head WhatsApp active number"), "9999999999");
    fireEvent.submit(screen.getByRole("button", { name: "Submit Family Details" }).closest("form")!);
    await screen.findByRole("heading", { name: "Details Submitted" });
    expect(mocks.submit).toHaveBeenCalledTimes(2);
    expect(mocks.submit).toHaveBeenNthCalledWith(2, expect.objectContaining({ confirmed_fields: { given_names: "Rahul Example" }, family_head_name: "Asha Example", submission_mode: "family" }));
  });

  it("keeps a family record out of the single-traveller review when changing submission mode", async () => {
    render(<UploadFlow token="test-token" />);
    await userEvent.click(await screen.findByRole("button", { name: /Family/ }));
    const names = screen.getAllByPlaceholderText("Full name");
    await userEvent.type(names[0], "Asha Example");
    await userEvent.type(names[1], "Rahul Example");
    await userEvent.selectOptions(screen.getAllByLabelText("Gender")[0], "Female");
    await userEvent.selectOptions(screen.getAllByLabelText("Gender")[1], "Male");
    await userEvent.selectOptions(screen.getAllByLabelText("Relation")[1], "Spouse");
    await userEvent.click(screen.getByRole("button", { name: "Continue to Documents" }));
    await userEvent.click(screen.getByRole("button", { name: "Continue to your details" }));
    await waitFor(() => expect(mocks.upload).toHaveBeenCalledTimes(1));
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    await userEvent.click(screen.getByRole("button", { name: /Single/ }));
    expect(screen.queryByRole("button", { name: "Resume review" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue to your details" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Full name/)).toHaveValue("");
  });

  it("keeps selected passport files and the idempotency key after an uncertain upload failure", async () => {
    mocks.group.upload_configuration = { ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: false, passport_upload_pages: ["cover"] };
    mocks.upload.mockRejectedValueOnce(new Error("Connection interrupted"));
    render(<UploadFlow token="test-token" />);
    await userEvent.click(await screen.findByRole("button", { name: /Single/ }));
    await userEvent.type(screen.getByLabelText(/Full name/), "Asha Example");
    await userEvent.click(screen.getByRole("button", { name: "Upload passport images" }));
    const cover = new File(["cover"], "cover.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Upload Passport Front Cover"), { target: { files: [cover] } });
    await userEvent.click(screen.getByRole("button", { name: "Save passport pages and continue" }));
    await userEvent.click(await screen.findByRole("button", { name: "Upload passport images" }));
    expect(screen.getByText("cover.jpg")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save passport pages and continue" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Save passport pages and continue" }));
    await screen.findByRole("heading", { name: "Review Traveller Details" });
    const attempts = mocks.upload.mock.calls.map(([attempt]) => attempt);
    expect(attempts).toHaveLength(2);
    expect(attempts[1].uploadIdempotencyKey).toBe(attempts[0].uploadIdempotencyKey);
    expect(attempts[1].passportCoverFile).toBe(cover);
  });
});
