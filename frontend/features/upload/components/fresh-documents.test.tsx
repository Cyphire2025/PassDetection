import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import type { FreshDraftState } from "../hooks/use-fresh-draft";
import { getUploadFlowSettings } from "../services/configured-upload";
import { FreshDocuments } from "./fresh-documents";
vi.mock("next/dynamic", () => ({ default: () => () => null }));
const state = { pending: false, draft: { documents: [] }, payload: { collection: { acquisition_mode: "file" } } } as unknown as FreshDraftState;
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
});
