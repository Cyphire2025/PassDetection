import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import type { PassportSubmission } from "@/types/passport.types";
import { UploadFlow } from "./upload-flow";

const mocks = vi.hoisted(() => ({
  group: {} as Record<string, unknown>,
  resume: null as PassportSubmission | null,
  upload: vi.fn(), submit: vi.fn(), getStatus: vi.fn(), scanAgain: vi.fn(),
  normalize: vi.fn(), report: vi.fn(), reportOnce: vi.fn(),
}));

vi.mock("@/features/passports/hooks/use-upload-links", () => ({ useUploadLinkByToken: () => ({ data: mocks.group, isLoading: false, error: null }) }));
vi.mock("../hooks/use-upload", () => ({ useUploadPassport: () => ({ mutateAsync: mocks.upload }), useSubmitClientPassportReview: () => ({ mutateAsync: mocks.submit }) }));
vi.mock("../hooks/use-public-flow-telemetry", () => ({ usePublicFlowTelemetry: () => ({ report: mocks.report, reportPublicFlowOnce: mocks.reportOnce }) }));
vi.mock("../api/upload.api", () => ({ uploadApi: { getUploadStatus: mocks.getStatus, scanAgain: mocks.scanAgain } }));
vi.mock("../services/passport-perspective-correction", () => ({ normalizePassportFile: mocks.normalize }));
vi.mock("./protected-upload-document-image", () => ({ ProtectedUploadDocumentImage: ({ alt }: { alt: string }) => <span>{alt}</span> }));
// Integration tests observe when the decorative component mounts; its artwork
// and visibility lifecycle are checked separately from this workflow boundary.
vi.mock("@/components/shared/processing-motion", () => ({ ProcessingMotion: ({ variant, compact }: { variant: string; compact?: boolean }) => <div data-testid="processing-motion" data-variant={variant} data-compact={Boolean(compact)} aria-hidden="true" /> }));
vi.mock("../services/upload-flow-bootstrap", () => ({
  runUploadFlowBootstrap: async ({ actions }: { actions: {
    setStep: (value: string) => void;
    setSubmission: (value: PassportSubmission) => void;
    setFlowMode: (value: string) => void;
    queueSubmissionResume: (value: PassportSubmission) => void;
  } }) => {
    await Promise.resolve();
    if (mocks.resume) {
      actions.setSubmission(mocks.resume);
      actions.setFlowMode("single");
      actions.queueSubmissionResume(mocks.resume);
      actions.setStep("UPLOADING");
    } else actions.setStep("MODE_SELECT");
  },
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((success, failure) => { resolve = success; reject = failure; });
  return { promise, resolve, reject };
}

function saved(overrides: Partial<PassportSubmission> = {}): PassportSubmission {
  return {
    id: "saved-passport", client_name: "Asha Example", image_s3_key: "saved-front.jpg",
    status: "pending_extraction", extraction_status: "processing", processing_stage: "extracting_passport_fields",
    processing_progress: 0.32, extracted_fields: null, ...overrides,
  } as PassportSubmission;
}

function completed(overrides: Partial<PassportSubmission> = {}) {
  return saved({
    status: "ready_for_client_review", extraction_status: "extraction_complete",
    extracted_fields: {
      given_names: "ASHA", surname: "EXAMPLE", passport_number: "A1234567", nationality: "IND",
      date_of_birth: "1990-01-01", date_of_issue: "2020-01-01", date_of_expiry: "2030-01-01",
      sex: "F", place_of_issue: "DELHI", place_of_birth: "DELHI",
      ai_verification: { available: true, status: "verified" },
    }, ...overrides,
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  window.sessionStorage.clear();
  mocks.resume = null;
  mocks.group = {
    id: "group-1", name: "Test Travel Group", token: "test-token", require_selfie: false, allow_files_from_device: true,
    upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: false, passport_upload_pages: ["front"], required_fields: {} },
  };
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:test-passport"), revokeObjectURL: vi.fn() }));
  mocks.normalize.mockImplementation(async (file: File) => ({ file }));
  mocks.upload.mockResolvedValue(saved());
  mocks.submit.mockResolvedValue({ status: "submitted" });
});

async function choosePassport() {
  await userEvent.click(screen.getByRole("button", { name: "Upload passport images" }));
  const passport = new File(["synthetic passport"], "passport.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByLabelText("Upload Personal Details Page"), { target: { files: [passport] } });
  await userEvent.click(screen.getByRole("button", { name: "Save passport pages and continue" }));
  return passport;
}

async function startSingle() {
  render(<UploadFlow token="test-token" />);
  await userEvent.click(await screen.findByRole("button", { name: /Single/ }));
  return choosePassport();
}

describe("passport extraction motion lifecycle", () => {
  it("starts only after image preparation and durable upload, then stops for review and final submission", async () => {
    const preparation = deferred<{ file: File }>();
    const upload = deferred<PassportSubmission>();
    const extraction = deferred<PassportSubmission>();
    const submission = deferred<{ status: string }>();
    mocks.normalize.mockReturnValue(preparation.promise);
    mocks.upload.mockReturnValue(upload.promise);
    mocks.getStatus.mockReturnValue(extraction.promise);
    mocks.submit.mockReturnValue(submission.promise);
    const passport = await startSingle();
    expect(mocks.normalize).toHaveBeenCalledWith(passport);
    expect(mocks.upload).not.toHaveBeenCalled();
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    await act(async () => preparation.resolve({ file: passport }));
    expect(screen.getByRole("heading", { name: "Saving Travel Documents" })).toBeInTheDocument();
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(mocks.getStatus).not.toHaveBeenCalled();
    await act(async () => upload.resolve(saved()));
    expect(screen.getByTestId("processing-motion")).toHaveAttribute("data-variant", "passport");
    expect(screen.getByRole("heading", { name: "Reading Passport Details" })).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "32");
    await waitFor(() => expect(mocks.getStatus).toHaveBeenCalledOnce());
    await act(async () => extraction.resolve(completed()));
    expect(screen.getByRole("heading", { name: "Verify Passport Details" })).toBeInTheDocument();
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Email"), "asha@example.com");
    await userEvent.type(screen.getByLabelText("WhatsApp active number"), "9999999999");
    fireEvent.submit(screen.getByRole("button", { name: "Submit Verified Details" }).closest("form")!);
    expect(screen.getByRole("heading", { name: "Submitting Reviewed Details" })).toBeInTheDocument();
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    await act(async () => submission.resolve({ status: "submitted" }));
    expect(screen.getByRole("heading", { name: "Details Submitted" })).toBeInTheDocument();
    expect(mocks.upload).toHaveBeenCalledOnce();
    expect(mocks.submit).toHaveBeenCalledOnce();
  });

  it("does not animate a failed upload or an already completed extraction", async () => {
    mocks.upload.mockRejectedValueOnce(new Error("Upload interrupted"));
    await startSingle();
    await screen.findByRole("button", { name: "Upload passport images" });
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(mocks.getStatus).not.toHaveBeenCalled();
    mocks.upload.mockResolvedValue(completed());
    await choosePassport();
    expect(await screen.findByRole("heading", { name: "Verify Passport Details" })).toBeInTheDocument();
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(mocks.getStatus).not.toHaveBeenCalled();
  });

  it("shows a compact scene only while a saved-image retry is being extracted and removes it on failure", async () => {
    mocks.upload.mockResolvedValue(saved({ status: "failed", extraction_status: "extraction_failed" }));
    const queued = deferred<PassportSubmission>();
    const extraction = deferred<PassportSubmission>();
    mocks.scanAgain.mockReturnValue(queued.promise);
    mocks.getStatus.mockReturnValue(extraction.promise);
    await startSingle();
    await userEvent.click(await screen.findByRole("button", { name: "Retry verification on saved image" }));
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    await act(async () => queued.resolve(saved()));
    expect(screen.getByTestId("processing-motion")).toHaveAttribute("data-compact", "true");
    await waitFor(() => expect(mocks.getStatus).toHaveBeenCalledOnce());
    await act(async () => extraction.reject({ code: "HTTP_403", message: "Session expired" }));
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry verification on saved image" })).toBeEnabled();
    expect(mocks.upload).toHaveBeenCalledOnce();
  });

  it("resumes the saved extraction scene and removes it when extraction fails terminally", async () => {
    const extraction = deferred<PassportSubmission>();
    mocks.resume = saved();
    mocks.getStatus.mockReturnValue(extraction.promise);
    render(<UploadFlow token="test-token" />);
    expect(await screen.findByTestId("processing-motion")).toHaveAttribute("data-compact", "false");
    await waitFor(() => expect(mocks.getStatus).toHaveBeenCalledOnce());
    await act(async () => extraction.resolve(saved({ status: "failed", extraction_status: "extraction_failed" })));
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry verification on saved image" })).toBeEnabled();
    expect(mocks.upload).not.toHaveBeenCalled();
  });

  it("keeps family retry motion attached to only the member being read", async () => {
    mocks.upload.mockResolvedValueOnce(completed({ id: "asha-passport" }))
      .mockResolvedValueOnce(saved({ id: "rahul-passport", status: "failed", extraction_status: "extraction_failed" }));
    const extraction = deferred<PassportSubmission>();
    mocks.scanAgain.mockResolvedValue(saved({ id: "rahul-passport" }));
    mocks.getStatus.mockReturnValue(extraction.promise);
    render(<UploadFlow token="test-token" />);
    await userEvent.click(await screen.findByRole("button", { name: /Family/ }));
    const names = screen.getAllByPlaceholderText("Full name");
    await userEvent.type(names[0], "Asha Example");
    await userEvent.type(names[1], "Rahul Example");
    await userEvent.selectOptions(screen.getAllByLabelText("Gender")[0], "Female");
    await userEvent.selectOptions(screen.getAllByLabelText("Gender")[1], "Male");
    await userEvent.selectOptions(screen.getAllByLabelText("Relation")[1], "Spouse");
    await userEvent.click(screen.getByRole("button", { name: "Continue to Documents" }));
    await choosePassport();
    await screen.findByRole("button", { name: "Upload passport images" });
    await choosePassport();
    await screen.findByRole("heading", { name: "Review Family Details" });
    await userEvent.click(screen.getByRole("button", { name: "Retry verification on saved image" }));
    const animation = await screen.findByTestId("processing-motion");
    const activeMember = animation.closest("section")!;
    expect(within(activeMember).getByText(/Rahul Example/)).toBeInTheDocument();
    expect(screen.getAllByTestId("processing-motion")).toHaveLength(1);
    await waitFor(() => expect(mocks.getStatus).toHaveBeenCalledOnce());
    await act(async () => extraction.resolve(completed({ id: "rahul-passport" })));
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Review Family Details" })).toBeInTheDocument();
    expect(mocks.upload).toHaveBeenCalledTimes(2);
  });
});
