import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VisaPhotoUpload } from "./visa-photo-upload";
import { preparePublicUploadFile } from "../services/public-upload-file";

vi.mock("../services/public-upload-file", () => ({
  preparePublicUploadFile: vi.fn(),
  PUBLIC_UPLOAD_ACCEPT: ".jpg,.jpeg,.png,.heic,.heif,.avif,.pdf",
}));

const NativeURL = globalThis.URL;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(preparePublicUploadFile).mockImplementation(async (file) => file);
  vi.stubGlobal("URL", Object.assign(class extends NativeURL {}, {
    createObjectURL: vi.fn(() => "blob:visa-photo-preview"),
    revokeObjectURL: vi.fn(),
  }));
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function pendingPreparation() {
  let resolve!: (result: File) => void;
  const promise = new Promise<File>((complete) => { resolve = complete; });
  vi.mocked(preparePublicUploadFile).mockReturnValueOnce(promise);
  return resolve;
}

describe("Visa Photo upload preview", () => {
  it("shows preparation, retains focus and permits the previewed file to continue", async () => {
    const user = userEvent.setup();
    const onCapture = vi.fn();
    const finishPreparation = pendingPreparation();
    const original = new File(["original"], "studio.jpg", { type: "image/jpeg" });
    const prepared = new File(["prepared"], "studio.jpg", { type: "image/jpeg" });
    render(<VisaPhotoUpload onCapture={onCapture} onCancel={() => {}} />);
    const input = screen.getByLabelText("Choose a studio Visa Photo") as HTMLInputElement;
    const openPicker = vi.spyOn(input, "click").mockImplementation(() => {});
    await user.click(screen.getByRole("button", { name: "Choose studio photo" }));
    expect(openPicker).toHaveBeenCalledOnce();
    fireEvent.change(input, { target: { files: [original] } });
    expect(screen.getByRole("group", { name: "Selected Visa Photo" })).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent("Preparing photo preview");
    expect(screen.getByRole("button", { name: "Choose another" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Use Visa Photo" })).not.toBeInTheDocument();
    await act(async () => { finishPreparation(prepared); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Use Visa Photo" }));
    expect(onCapture).toHaveBeenCalledExactlyOnceWith(prepared);
  });

  it("previews the full rendered PDF and passes that file on without cropping or photo verification", async () => {
    const onCapture = vi.fn();
    const pdf = new File(["%PDF"], "studio.pdf", { type: "application/pdf" });
    const rendered = new File(["landscape page with a photo anywhere"], "studio.jpg", { type: "image/jpeg" });
    vi.mocked(preparePublicUploadFile).mockResolvedValueOnce(rendered);
    render(<VisaPhotoUpload token="test-token" uploadSessionId="test-session" onCapture={onCapture} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Choose a studio Visa Photo"), { target: { files: [pdf] } });
    expect(await screen.findByRole("button", { name: "Use Visa Photo" })).toBeEnabled();
    expect(preparePublicUploadFile).toHaveBeenCalledWith(pdf, expect.objectContaining({ token: "test-token", uploadSessionId: "test-session", purpose: "visa" }));
    expect(URL.createObjectURL).toHaveBeenCalledExactlyOnceWith(rendered);
    expect(screen.getByRole("img", { name: "Selected Visa Photo preview" }).closest('[role="group"]')).toBe(screen.getByRole("group", { name: "Selected Visa Photo" }));
    expect(screen.getByText("Selected: studio.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use Visa Photo" }));
    expect(onCapture).toHaveBeenCalledExactlyOnceWith(rendered);
    expect(screen.queryByText(/checks passed|verifying/i)).not.toBeInTheDocument();
  });

  it("still shows file-limit errors and prevents confirmation when preparation fails", async () => {
    vi.mocked(preparePublicUploadFile).mockRejectedValueOnce({ code: "HTTP_400", message: "PDFs must contain exactly one page." });
    render(<VisaPhotoUpload onCapture={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Choose a studio Visa Photo"), { target: { files: [new File(["pdf"], "two.pdf", { type: "application/pdf" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("PDFs must contain exactly one page.");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Use Visa Photo" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose another" })).toBeEnabled();
  });

  it("clears the previous selection while preparing a replacement", async () => {
    render(<VisaPhotoUpload onCapture={() => {}} onCancel={() => {}} />);
    const input = screen.getByLabelText("Choose a studio Visa Photo");
    fireEvent.change(input, { target: { files: [new File(["first"], "first.jpg")] } });
    await screen.findByRole("button", { name: "Use Visa Photo" });
    const finishPreparation = pendingPreparation();
    fireEvent.change(input, { target: { files: [new File(["second"], "second.jpg")] } });
    expect(screen.queryByRole("button", { name: "Use Visa Photo" })).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:visa-photo-preview");
    const replacement = new File(["second preview"], "second.jpg");
    await act(async () => { finishPreparation(replacement); });
    expect(screen.getByRole("button", { name: "Use Visa Photo" })).toBeEnabled();
    expect(screen.getByText("Selected: second.jpg")).toBeInTheDocument();
  });

  it("aborts preparation and ignores a late result after the dialog closes", async () => {
    const finishPreparation = pendingPreparation();
    const view = render(<VisaPhotoUpload onCapture={() => {}} onCancel={() => {}} />);
    fireEvent.change(screen.getByLabelText("Choose a studio Visa Photo"), { target: { files: [new File(["pdf"], "photo.pdf", { type: "application/pdf" })] } });
    await waitFor(() => expect(preparePublicUploadFile).toHaveBeenCalledOnce());
    const options = vi.mocked(preparePublicUploadFile).mock.calls[0][1];
    view.unmount();
    expect(options.signal?.aborted).toBe(true);
    await act(async () => { finishPreparation(new File(["jpeg"], "photo.jpg", { type: "image/jpeg" })); });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
