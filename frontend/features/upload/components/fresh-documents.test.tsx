import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import type { FreshDraftState } from "../hooks/use-fresh-draft";
import { getUploadFlowSettings } from "../services/configured-upload";
import { FreshDocuments } from "./fresh-documents";
import { UPLOAD_INSTRUCTIONS } from "../config/instruction-translations";
import { VISA_PHOTO_GUIDELINES } from "../config/visa-photo-guidelines";
vi.mock("next/dynamic", () => ({ default: () => () => null }));
const state = { pending: false, draft: { documents: [] }, payload: { collection: { acquisition_mode: "file" } } } as unknown as FreshDraftState;
beforeEach(() => sessionStorage.clear());
describe("fresh configured document choices", () => {
  it("preserves live-only passport and photo collection without a file fallback", () => {
    const settings = getUploadFlowSettings({ allow_files_from_device: false, require_selfie: true, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, visa_photo_upload: false } } as UploadLinkResponse);
    render(<FreshDocuments state={state} settings={settings} token="trip" sessionId="member" />);
    expect(screen.getAllByRole("button", { name: "Use camera" })).toHaveLength(3);
    expect(document.querySelectorAll('input[type="file"]')).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "Personal Details Page" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Address Details Page" })).toBeVisible();
  });
  it("respects passport-disabled and photo-upload-only configurations", () => {
    const settings = getUploadFlowSettings({ allow_files_from_device: true, require_selfie: true, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_enabled: false, visa_photo_live_capture: false } } as UploadLinkResponse);
    render(<FreshDocuments state={state} settings={settings} token="trip" sessionId="member" />);
    expect(screen.queryByRole("heading", { name: "Personal Details Page" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Upload traveller photo")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Use camera" })).not.toBeInTheDocument();
  });
  it("restores link-specific translated guidance before the actual upload controls", () => {
    sessionStorage.setItem("passdetection:instruction-language:trip", "ur");
    const settings = getUploadFlowSettings({ allow_files_from_device: true, require_selfie: true, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, instruction_languages_enabled: true, instruction_languages: ["mr", "ur"] } } as UploadLinkResponse);
    const view = render(<FreshDocuments state={state} settings={settings} token="trip" sessionId="member" />);
    expect(screen.getByRole("combobox", { name: "Instruction language" })).toHaveValue("ur");
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.ur.passportIntro)).toHaveAttribute("dir", "rtl");
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.ur.front)).toHaveAttribute("lang", "ur");
    const guidelines = screen.getByRole("region", { name: VISA_PHOTO_GUIDELINES.ur.heading });
    expect(within(guidelines).getAllByRole("listitem")).toHaveLength(6);
    expect(guidelines.compareDocumentPosition(screen.getByLabelText("Upload traveller photo")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Traveller photo" }).closest('[dir="rtl"]')).toBeNull();
    fireEvent.change(screen.getByRole("combobox", { name: "Instruction language" }), { target: { value: "mr" } });
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.mr.visaWarning)).toBeVisible();
    view.rerender(<FreshDocuments state={state} settings={settings} token="other-trip" sessionId="member" />);
    expect(screen.getByRole("combobox", { name: "Instruction language" })).toHaveValue("en");
  });
  it("ignores a stored translation when the link disables language choices", () => {
    sessionStorage.setItem("passdetection:instruction-language:trip", "mr");
    const settings = getUploadFlowSettings({ upload_configuration: DEFAULT_UPLOAD_CONFIGURATION } as UploadLinkResponse);
    render(<FreshDocuments state={state} settings={settings} token="trip" sessionId="member" />);
    expect(screen.queryByRole("combobox", { name: "Instruction language" })).not.toBeInTheDocument();
    expect(screen.getByText(UPLOAD_INSTRUCTIONS.en.passportIntro)).toBeVisible();
  });
});
