import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import type { DraftDocumentInputs } from "../services/draft-input-contract";
import { getUploadFlowSettings } from "../services/configured-upload";
import { preparePublicUploadFile } from "../services/public-upload-file";
import { FreshDocuments } from "./fresh-documents";
vi.mock("next/dynamic", () => ({ default: () => () => null }));
vi.mock("../services/public-upload-file", async (original) => ({ ...await original<object>(), preparePublicUploadFile: vi.fn(async (file: File) => file) }));
const settings = getUploadFlowSettings({ allow_files_from_device: true, require_selfie: true, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_ecr_enabled: true, passport_upload_pages: ["back_cover", "back", "cover", "front"] } } as UploadLinkResponse);
const makeState = (): DraftDocumentInputs => ({ pending: false, draft: { documents: [] }, payload: { passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {}, collection: { acquisition_mode: "file", submission_mode: "single" } }, collection: vi.fn(), upload: vi.fn(async (side) => ({ documents: [{ id: `new-${side}`, side, state: "ready" as const }] })), api: { document: vi.fn(async () => new Blob(["synthetic"], { type: "image/jpeg" })) } });
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn((file: File) => `blob:${file.name ?? "saved"}`), revokeObjectURL: vi.fn() }));
  vi.stubGlobal("IntersectionObserver", undefined);
});
describe("ordered document processing", () => {
  it("orders enabled previews consistently and allows the address page before the details page", () => {
    render(<FreshDocuments state={makeState()} settings={settings} token="trip" sessionId="session" />);
    expect(Array.from(document.querySelectorAll('[data-document-side]')).map((element) => element.getAttribute('data-document-side'))).toEqual(["photo", "front", "back", "cover", "back_cover"]);
    expect(screen.getByLabelText("Upload address details page")).toBeEnabled();
  });
  it("shows the selected image immediately, waits for processing, and releases it on leaving", async () => {
    let finish!: (file: File) => void, finishUpload!: (receipt: { documents: [{ id: string; side: "front"; state: "ready" }] }) => void;
    vi.mocked(preparePublicUploadFile).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const state = makeState();
    vi.mocked(state.upload).mockImplementationOnce(() => new Promise((resolve) => { finishUpload = resolve; }));
    const view = render(<FreshDocuments state={state} settings={settings} token="trip" sessionId="session" />);
    const file = new File(["synthetic"], "new-front.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [file] } });
    expect(await screen.findByRole("img", { name: "Passport details page" })).toHaveAttribute("src", "blob:new-front.jpg");
    expect(screen.getByText("Extracting details…")).toBeVisible();
    expect(state.upload).not.toHaveBeenCalled();
    await act(async () => finish(file));
    await waitFor(() => expect(state.upload).toHaveBeenCalledExactlyOnceWith("front", file));
    expect(screen.getByText("Extracting details…")).toBeVisible();
    const documents = [{ id: "new-front", side: "front" as const, state: "ready" as const }] as [{ id: string; side: "front"; state: "ready" }];
    await act(async () => finishUpload({ documents }));
    view.rerender(<FreshDocuments state={{ ...state, draft: { documents, extraction_status: "pending" } }} settings={settings} token="trip" sessionId="session" />);
    expect(screen.getByText("Extracting details…")).toBeVisible();
    view.rerender(<FreshDocuments state={{ ...state, draft: { documents: [{ id: "new-front", side: "front", state: "ready" }], extraction_status: "running" } }} settings={settings} token="trip" sessionId="session" />);
    expect(screen.getByText("Extracting details…")).toBeVisible();
    expect(screen.getByRole("img", { name: "Passport details page" })).toHaveAttribute("src", "blob:new-front.jpg");
    expect(screen.getByRole("img", { name: "Passport details page" }).closest('[aria-busy]')).toHaveAttribute("aria-busy", "true");
    view.rerender(<FreshDocuments state={{ ...state, draft: { documents, extraction_status: "succeeded" } }} settings={settings} token="trip" sessionId="session" />);
    expect(screen.queryByText("Extracting details…")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Passport details page" }).closest('[aria-busy]')).toHaveAttribute("aria-busy", "false");
    view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:new-front.jpg");
  });
  it("shows the real ECR checking status only on enabled address-page checks", async () => {
    const state = makeState(); state.draft = { documents: [{ id: "back", side: "back", state: "ready" }], ecr_status: "running" };
    const view = render(<FreshDocuments state={state} settings={settings} token="trip" sessionId="session" />);
    expect(await screen.findByRole("img", { name: "Passport address page" })).toBeVisible();
    expect(screen.getByText("Verifying ECR presence…")).toBeVisible();
    view.rerender(<FreshDocuments state={state} settings={{ ...settings, uploadConfig: { ...settings.uploadConfig, passport_ecr_enabled: false } }} token="trip" sessionId="session" />);
    expect(screen.queryByText("Verifying ECR presence…")).not.toBeInTheDocument();
  });
  it.each([true, false])("keeps the correct address-page stage through transfer with ECR enabled=%s", async (ecr) => {
    let finish!: (file: File) => void;
    vi.mocked(preparePublicUploadFile).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const state = makeState(), configured = { ...settings, uploadConfig: { ...settings.uploadConfig, passport_ecr_enabled: ecr } };
    const view = render(<FreshDocuments state={state} settings={configured} token="trip" sessionId="session" />);
    const file = new File(["address"], "address.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Upload address details page"), { target: { files: [file] } });
    expect(await screen.findByText(ecr ? "Verifying ECR presence…" : "Uploading document…")).toBeVisible();
    await act(async () => finish(file));
    await waitFor(() => expect(state.upload).toHaveBeenCalledExactlyOnceWith("back", file));
    const documents = [{ id: "new-back", side: "back" as const, state: "ready" as const }];
    view.rerender(<FreshDocuments state={{ ...state, draft: { documents, ecr_status: ecr ? "failed" : "none" } }} settings={configured} token="trip" sessionId="session" />);
    expect(screen.queryByText("Verifying ECR presence…")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Passport address page" }).closest('[aria-busy]')).toHaveAttribute("aria-busy", "false");
    if (ecr) expect(screen.getByRole("alert")).toHaveTextContent("couldn’t check ECR");
  });
  it("rolls back a failed local selection instead of presenting it as a saved upload", async () => {
    const state = makeState(); vi.mocked(state.upload).mockRejectedValueOnce(new Error("Upload interrupted"));
    render(<FreshDocuments state={state} settings={settings} token="trip" sessionId="session" />);
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [new File(["synthetic"], "failed.jpg", { type: "image/jpeg" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Upload interrupted");
    expect(screen.queryByRole("img", { name: "Passport details page" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Upload personal details page")).toBeEnabled();
  });
  it("clears an unfinished image when the page leaves, including a bfcache departure", async () => {
    vi.mocked(preparePublicUploadFile).mockImplementationOnce(() => new Promise(() => undefined));
    render(<FreshDocuments state={makeState()} settings={settings} token="trip" sessionId="session" />);
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [new File(["synthetic"], "abandoned.jpg", { type: "image/jpeg" })] } });
    expect(await screen.findByRole("img", { name: "Passport details page" })).toBeVisible();
    fireEvent(window, new Event("pagehide"));
    expect(screen.queryByRole("img", { name: "Passport details page" })).not.toBeInTheDocument();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:abandoned.jpg");
  });

  it("binds the local preview to its accepted image and never restores it over a newer remote image", async () => {
    const state = makeState();
    const view = render(<FreshDocuments state={state} settings={settings} token="trip" sessionId="session" />);
    const image = (name: string) => new File([name], name, { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [image("accepted-A.jpg")] } });
    await waitFor(() => expect(state.upload).toHaveBeenCalledOnce());
    state.draft = { documents: [{ id: "new-front", side: "front", state: "ready" }] };
    view.rerender(<FreshDocuments state={state} settings={settings} token="trip" sessionId="session" />);
    expect(await screen.findByRole("img", { name: "Passport details page" })).toHaveAttribute("src", "blob:accepted-A.jpg");
    expect(state.api.document).not.toHaveBeenCalled();

    state.draft = { documents: [{ id: "remote-B", side: "front", state: "ready" }] };
    view.rerender(<FreshDocuments state={state} settings={settings} token="trip" sessionId="session" />);
    await waitFor(() => expect(state.api.document).toHaveBeenCalledWith("remote-B", expect.any(AbortSignal)));
    expect(await screen.findByRole("img", { name: "Passport details page" })).toHaveAttribute("src", "blob:saved");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:accepted-A.jpg");

    vi.mocked(state.upload).mockRejectedValueOnce(new Error("Replacement C interrupted"));
    fireEvent.change(screen.getByLabelText("Upload personal details page"), { target: { files: [image("failed-C.jpg")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Replacement C interrupted");
    await waitFor(() => expect(screen.getByRole("img", { name: "Passport details page" })).toHaveAttribute("src", "blob:saved"));
    expect(screen.queryByRole("img", { name: "Passport details page" })).not.toHaveAttribute("src", "blob:accepted-A.jpg");
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:failed-C.jpg");
  });
});
