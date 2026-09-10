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
