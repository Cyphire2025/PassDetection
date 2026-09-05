import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import { emptyDocumentBundle } from "../services/upload-flow-helpers";
import { UploadDocumentOptions } from "./upload-flow-document-options";
import { VisaSelfieChoice } from "./upload-flow-passport-picker";

const methodConfigurations = [
  { name: "camera only", camera: true, upload: false },
  { name: "upload only", camera: false, upload: true },
  { name: "both methods", camera: true, upload: true },
];

describe("document method cards", () => {
  it.each(methodConfigurations)("preserves Visa Photo actions for $name", async ({ camera, upload }) => {
    const onCameraClick = vi.fn();
    const onUploadClick = vi.fn();
    render(<VisaSelfieChoice file={null} allowCamera={camera} allowUpload={upload} required onCameraClick={onCameraClick} onUploadClick={onUploadClick} />);

    const card = within(screen.getByTestId("visa-photo-choice"));
    expect(card.getByText("Required", { exact: true })).toBeInTheDocument();
    expect(card.getAllByRole("button")).toHaveLength(Number(camera) + Number(upload));
    if (camera) await userEvent.click(card.getByRole("button", { name: "Use live camera" }));
    else expect(card.queryByRole("button", { name: "Use live camera" })).not.toBeInTheDocument();
    if (upload) await userEvent.click(card.getByRole("button", { name: "Upload studio photo" }));
    else expect(card.queryByRole("button", { name: "Upload studio photo" })).not.toBeInTheDocument();
    expect(onCameraClick).toHaveBeenCalledTimes(Number(camera));
    expect(onUploadClick).toHaveBeenCalledTimes(Number(upload));
  });

  it.each(methodConfigurations)("preserves passport actions and contextual guidance for $name", async ({ camera, upload }) => {
    const onScan = vi.fn();
    const onOpenUpload = vi.fn();
    render(<UploadDocumentOptions
      config={{ ...DEFAULT_UPLOAD_CONFIGURATION, passport_live_scan: camera }}
      allowFilesFromDevice={upload} flowMode="single" clientName="Asha Example" onClientName={() => {}}
      passportMethod="file" bundle={emptyDocumentBundle()} onBundleChange={() => {}}
      onScan={onScan} onFileSelect={() => {}} onUpload={() => {}} onOpenUpload={onOpenUpload} onSkip={() => {}}
    />);

    const card = within(screen.getByTestId("passport-document-choice"));
    expect(card.getByRole("heading", { name: "Passport" })).toBeInTheDocument();
    expect(card.getByText("Required", { exact: true })).toBeInTheDocument();
    expect(card.getByText(/Keep each page fully visible/)).toBeInTheDocument();
    expect(card.getAllByRole("button")).toHaveLength(Number(camera) + Number(upload));
    if (camera) {
      await userEvent.click(card.getByRole("button", { name: "Live scan" }));
      expect(onScan).toHaveBeenCalledWith("front");
    } else expect(card.queryByRole("button", { name: "Live scan" })).not.toBeInTheDocument();
    if (upload) {
      await userEvent.click(card.getByRole("button", { name: "Upload passport images" }));
      expect(card.getByText(/2 MB or smaller per page/)).toBeInTheDocument();
    } else {
      expect(card.queryByRole("button", { name: "Upload passport images" })).not.toBeInTheDocument();
      expect(card.queryByText(/2 MB or smaller per page/)).not.toBeInTheDocument();
    }
    expect(onScan).toHaveBeenCalledTimes(Number(camera));
    expect(onOpenUpload).toHaveBeenCalledTimes(Number(upload));
    expect(screen.queryByRole("button", { name: "Continue without passport" })).not.toBeInTheDocument();
  });
});
