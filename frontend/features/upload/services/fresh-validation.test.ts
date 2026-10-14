import { describe, expect, it } from "vitest";
import type { FreshDraft } from "../api/fresh-draft.api";
import { freshValidation } from "./fresh-validation";
import { getUploadFlowSettings } from "./configured-upload";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";

const group = { upload_configuration: DEFAULT_UPLOAD_CONFIGURATION, custom_questions: [], custom_details: [] } as unknown as UploadLinkResponse;
const draft = (): FreshDraft => ({ id: "draft", revision: 1, expires_at: "2099-01-01", status: "active", verified_phone: null, collection: { acquisition_mode: "file", submission_mode: "single" }, passport_fields: { given_names: "Person", surname: "Example", passport_number: "P123", nationality: "IND", place_of_issue: "DELHI", date_of_birth: "1990-01-01", date_of_issue: "2020-01-01", date_of_expiry: "2030-01-01", sex: "M" }, current_details: {}, custom_answers: {}, custom_detail_answers: {}, documents: [{ id: "front", side: "front", state: "ready" }, { id: "back", side: "back", state: "ready" }], extracted_fields: {}, extraction_status: "succeeded" });
describe("fresh final validation uses existing group requirements", () => {
  it("requires all configured pages and completed extraction without inventing a submission", () => {
    const value = draft(), settings = getUploadFlowSettings(group);
    expect(freshValidation(settings, value, value)).toBeNull();
    value.documents.pop(); expect(freshValidation(settings, value, value)).toMatch(/every requested/);
    value.documents.push({ id: "back", side: "back", state: "ready" }); value.extraction_status = "running";
    expect(freshValidation(settings, value, value)).toMatch(/check to finish/);
  });
  it("uses shared required custom and configured-field validation", () => {
    const value = draft(), settings = getUploadFlowSettings({ ...group, staff_code_enabled: true, custom_details: [{ id: "region", label: "Region", enabled: true, required: true }] });
    expect(freshValidation(settings, value, value)).toMatch(/staff code/);
    value.current_details.staff_code = "STAFF-1"; expect(freshValidation(settings, value, value)).toMatch(/custom detail/);
    value.custom_detail_answers.region = "North"; expect(freshValidation(settings, value, value)).toBeNull();
  });
  it("supports optional passport while keeping family and qualifier requirements", () => {
    const value = draft(); value.documents = []; value.current_details.client_name = "Example Person";
    const settings = getUploadFlowSettings({ ...group, relation_with_qualifier_enabled: true, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, passport_enabled: false } });
    expect(freshValidation(settings, value, value)).toMatch(/qualifier/);
    value.collection!.qualifier_selection_token = "opaque"; value.collection!.submission_mode = "family";
    expect(freshValidation(settings, value, value)).toMatch(/relationship and gender/);
    value.collection!.family_relation = "Head"; value.collection!.family_gender = "Male";
    expect(freshValidation(settings, value, value)).toBeNull();
  });
});
