import { describe, expect, it } from "vitest";
import { getUploadFlowSettings } from "./configured-upload";
import { configuredReviewError, type ConfiguredReviewDraft } from "./review-submission-validation";

const draft = (): ConfiguredReviewDraft => ({ baseCity: "", nearestDomesticAirport: "", staffCode: "", agentEmployeeCode: "", designation: "", agencyDealershipName: "", mealPreference: "", customAnswers: {}, customDetailAnswers: {} });
function fixture() { return { draft: draft(), settings: getUploadFlowSettings() }; }

describe("current private draft configured-field validation", () => {
  it.each([
    ["baseCityEnabled", "base_city", "baseCity"],
    ["askNearestDomesticAirport", "nearest_domestic_airport", "nearestDomesticAirport"],
    ["staffCodeEnabled", "staff_code", "staffCode"],
    ["agentEmployeeCodeEnabled", "agent_employee_code", "agentEmployeeCode"],
    ["designationEnabled", "designation", "designation"],
    ["agencyDealershipNameEnabled", "agency_dealership_name", "agencyDealershipName"],
    ["mealPreferenceEnabled", "meal_preference", "mealPreference"],
  ] as const)("enforces enabled %s and preserves optional configuration", (enabled, field, value) => {
    const input = fixture(); input.settings[enabled] = true;
    input.settings.uploadConfig.required_fields = { [field]: true };
    expect(configuredReviewError(input.settings, input.draft)).toBeTruthy();
    input.draft[value] = "Filled";
    expect(configuredReviewError(input.settings, input.draft)).toBeNull();
    input.settings.uploadConfig.required_fields = { [field]: false }; input.draft[value] = "";
    expect(configuredReviewError(input.settings, input.draft)).toBeNull();
  });
  it("requires enabled custom answers and preserves the configured field label", () => {
    const input = fixture();
    input.settings.enabledCustomQuestions = [{ id: "question", label: "Question", enabled: true, required: true, options: ["Yes"] }];
    input.settings.enabledCustomDetails = [{ id: "detail", label: "Detail", enabled: true, required: true }];
    expect(configuredReviewError(input.settings, input.draft)).toContain("custom question");
    input.draft.customAnswers.question = "Yes";
    expect(configuredReviewError(input.settings, input.draft)).toContain("custom detail");
    input.draft.customDetailAnswers.detail = "Filled";
    expect(configuredReviewError(input.settings, input.draft)).toBeNull();
    input.settings.agentEmployeeCodeEnabled = true; input.settings.uploadConfig.required_fields = { agent_employee_code: true };
    input.settings.uploadConfig.agent_employee_code_label = "Producer Code";
    expect(configuredReviewError(input.settings, input.draft)).toBe("Please enter your producer code.");
  });
  it("does not require disabled fields or explicitly optional custom answers", () => {
    const input = fixture(); input.settings.uploadConfig.required_fields = { staff_code: true };
    input.settings.enabledCustomQuestions = [{ id: "question", label: "Question", enabled: true, required: false, options: ["Yes"] }];
    input.settings.enabledCustomDetails = [{ id: "detail", label: "Detail", enabled: true, required: false }];
    expect(configuredReviewError(input.settings, input.draft)).toBeNull();
  });
});
