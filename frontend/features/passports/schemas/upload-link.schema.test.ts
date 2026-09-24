import { describe, expect, it } from "vitest";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../types/upload-configuration";
import { createUploadLinkSchema, uploadConfigurationSchema } from "./upload-link.schema";

const validLink = {
  name: "Dubai group", destination: "Dubai", travel_date: "2026-11-01", return_date: "2026-11-08", timezone: "Asia/Kolkata",
  departure_cities: [], base_city_enabled: false, nearest_international_airport_enabled: false,
  staff_code_enabled: false, agent_employee_code_enabled: false, meal_preference_enabled: false,
  require_selfie: false, allow_files_from_device: true, ask_nearest_domestic_airport: false,
  relation_with_qualifier_enabled: true, designation_enabled: false, agency_dealership_name_enabled: false,
  custom_questions: [], custom_details: [], whatsapp_broadcast_group_ids: [],
};

describe("ECR and instruction language configuration", () => {
  it("defaults older configurations to disabled features and clones empty language selections", () => {
    const legacy = Object.fromEntries(Object.entries(DEFAULT_UPLOAD_CONFIGURATION).filter(([key]) => !key.startsWith("instruction_") && key !== "passport_ecr_enabled"));
    expect(uploadConfigurationSchema.parse(legacy)).toMatchObject({ passport_ecr_enabled: false, instruction_languages_enabled: false, instruction_languages: [] });
  });

  it("requires Passport and its address page for ECR when device upload is allowed", () => {
    const config = { ...DEFAULT_UPLOAD_CONFIGURATION, passport_ecr_enabled: true, passport_upload_pages: ["front"] };
    expect(createUploadLinkSchema.safeParse({ ...validLink, upload_configuration: config }).success).toBe(false);
    expect(createUploadLinkSchema.safeParse({ ...validLink, allow_files_from_device: false, upload_configuration: config }).success).toBe(true);
    expect(uploadConfigurationSchema.safeParse({ ...config, passport_enabled: false }).success).toBe(false);
    expect(createUploadLinkSchema.safeParse({ ...validLink, upload_configuration: { ...config, passport_upload_pages: ["front", "back"] } }).success).toBe(true);
  });

  it("requires a selected additional language only while the feature is enabled", () => {
    expect(uploadConfigurationSchema.safeParse({ ...DEFAULT_UPLOAD_CONFIGURATION, instruction_languages_enabled: true }).success).toBe(false);
    const selected = uploadConfigurationSchema.parse({ ...DEFAULT_UPLOAD_CONFIGURATION, instruction_languages_enabled: true, instruction_languages: ["ur", "hi", "mr"] });
    expect(selected.instruction_languages).toEqual(["mr", "hi", "ur"]);
    expect(uploadConfigurationSchema.parse({ ...selected, instruction_languages_enabled: false }).instruction_languages).toEqual(["mr", "hi", "ur"]);
  });

  it.each([{ instruction_languages: ["en"] }, { instruction_languages: ["fr"] }, { instruction_languages: ["hi", "hi"] }, { instruction_languages: ["MR"] }])("rejects unsupported or duplicate language codes %j", ({ instruction_languages }) => {
    expect(uploadConfigurationSchema.safeParse({ ...DEFAULT_UPLOAD_CONFIGURATION, instruction_languages }).success).toBe(false);
  });
});

describe("import data groups", () => {
  const details = { name: "Final roster", destination: "Dubai", travel_date: "2026-11-01", return_date: "2026-11-08", timezone: "Asia/Kolkata", import_only: true };

  it("accepts only the five group details and disables document collection", () => {
    expect(createUploadLinkSchema.parse(details)).toMatchObject({
      ...details, require_selfie: false, allow_files_from_device: false,
      custom_questions: [], custom_details: [], departure_cities: [],
      whatsapp_broadcast_group_ids: [], matching_fields_by_broadcast: {},
      upload_configuration: { passport_enabled: false, passport_required: false, passport_live_scan: false, passport_upload_pages: [], visa_photo_upload: false },
    });
  });

  it("ignores invalid hidden fields instead of validating or retaining them", () => {
    const parsed = createUploadLinkSchema.parse({
      ...details, upload_configuration: { agent_employee_code_label: "" },
      custom_questions: [{ label: "" }], custom_details: null,
      departure_cities: [""], nearest_international_airport_enabled: true,
      whatsapp_broadcast_group_ids: ["not-a-uuid"], matching_fields_by_broadcast: { invalid: [] },
      notes: "hidden notes",
    });
    expect(parsed).toMatchObject({ custom_questions: [], custom_details: [], nearest_international_airport_enabled: false, whatsapp_broadcast_group_ids: [] });
    expect(parsed).not.toHaveProperty("notes");
  });

  it.each([
    { name: " " }, { destination: " " }, { travel_date: "" }, { return_date: "" },
    { timezone: "not-a-timezone" }, { return_date: "2026-10-01" },
  ])("still validates required trip details %j", (invalid) => {
    expect(createUploadLinkSchema.safeParse({ ...details, ...invalid }).success).toBe(false);
  });
});

describe("qualifier relationship configuration", () => {
  it("parses older configurations with list-only defaults", () => {
    const legacyConfiguration = Object.fromEntries(Object.entries(DEFAULT_UPLOAD_CONFIGURATION).filter(([key]) => !key.startsWith("qualifier_relation_")));
    expect(uploadConfigurationSchema.parse(legacyConfiguration)).toEqual(DEFAULT_UPLOAD_CONFIGURATION);
    expect(createUploadLinkSchema.safeParse({ ...validLink, upload_configuration: legacyConfiguration }).success).toBe(true);
    expect(createUploadLinkSchema.safeParse(validLink).success).toBe(true);
  });

  it.each([
    [true, false, true],
    [false, true, true],
    [true, true, true],
    [false, false, false],
  ])("validates and preserves relationship methods list=%s other=%s", (list, other, valid) => {
    const input = { ...validLink, upload_configuration: { ...DEFAULT_UPLOAD_CONFIGURATION, qualifier_relation_list_enabled: list, qualifier_relation_other_enabled: other } };
    const result = createUploadLinkSchema.safeParse(input);
    expect(result.success).toBe(valid);
    if (result.success) {
      expect(result.data.upload_configuration).toMatchObject({ qualifier_relation_list_enabled: list, qualifier_relation_other_enabled: other });
    } else {
      expect(result.error.issues).toContainEqual(expect.objectContaining({ path: ["upload_configuration"], message: "Enable at least one option for Relation with Qualifier." }));
    }
    expect(createUploadLinkSchema.safeParse({ ...input, relation_with_qualifier_enabled: false }).success).toBe(true);
  });

  it.each(["true", 1, null])("rejects a non-boolean method flag %s", (value) => {
    expect(uploadConfigurationSchema.safeParse({ ...DEFAULT_UPLOAD_CONFIGURATION, qualifier_relation_other_enabled: value }).success).toBe(false);
  });
});

describe("WhatsApp identification field configuration", () => {
  const broadcastId = "0d252766-b75b-4698-8502-92ea0c339f15";

  it("defaults older create payloads to no explicit per-broadcast configuration", () => {
    const result = createUploadLinkSchema.parse(validLink);
    expect(result.matching_fields_by_broadcast).toEqual({});
  });

  it("preserves one or more selected spreadsheet headings for a linked broadcast", () => {
    const result = createUploadLinkSchema.parse({
      ...validLink,
      whatsapp_broadcast_group_ids: [broadcastId],
      matching_fields_by_broadcast: {
        [broadcastId]: ["name", "mobile_number", "producer_code"],
      },
    });
    expect(result.matching_fields_by_broadcast).toEqual({
      [broadcastId]: ["name", "mobile_number", "producer_code"],
    });
  });

  it("rejects empty field selections instead of silently replacing configured matching", () => {
    const result = createUploadLinkSchema.safeParse({
      ...validLink,
      whatsapp_broadcast_group_ids: [broadcastId],
      matching_fields_by_broadcast: { [broadcastId]: [] },
    });
    expect(result.success).toBe(false);
  });

  it("rejects identification fields for a broadcast that is no longer linked", () => {
    const result = createUploadLinkSchema.safeParse({
      ...validLink,
      matching_fields_by_broadcast: { [broadcastId]: ["producer_code"] },
    });
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues).toContainEqual(expect.objectContaining({
        path: ["matching_fields_by_broadcast", broadcastId],
      }));
    }
  });
});
