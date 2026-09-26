import { describe, expect, it } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { getUploadFlowSettings } from "./configured-upload";
import { createFamilyMembers } from "./upload-flow-helpers";
import { configuredReviewError, validateFamilyReview, validateSingleReview, type SingleReviewDraft } from "./review-submission-validation";

const draft = (): SingleReviewDraft => ({ clientName: "Synthetic Traveller", clientEmail: "synthetic@example.com", clientPhone: "+919999999999", reviewFields: {},
  departureCity: "", baseCity: "", nearestDomesticAirport: "", staffCode: "", agentEmployeeCode: "", designation: "", agencyDealershipName: "", mealPreference: "", customAnswers: {}, customDetailAnswers: {} });
const saved = { id: "saved", image_s3_key: "", status: "ready_for_client_review" } as PassportSubmission;
function fixture() {
  const familyMembers = createFamilyMembers(2).map((member, index) => ({ ...member, name: `Synthetic ${index}`, email: "synthetic@example.com", phone: "+919999999999", submission: saved }));
  return { draft: draft(), settings: getUploadFlowSettings(), submission: saved, familyMembers,
    requiresPassportReview: () => false, canReviewSubmission: () => true };
}

describe("shared review validation", () => {
  it("accepts complete optional-passport single and family reviews", () => {
    const input = fixture();
    expect(validateSingleReview(input)).toBeNull();
    expect(validateFamilyReview(input)).toBeNull();
  });
  it.each([
    ["baseCityEnabled", "base_city", "baseCity"],
    ["askNearestDomesticAirport", "nearest_domestic_airport", "nearestDomesticAirport"],
    ["staffCodeEnabled", "staff_code", "staffCode"],
    ["agentEmployeeCodeEnabled", "agent_employee_code", "agentEmployeeCode"],
    ["designationEnabled", "designation", "designation"],
    ["agencyDealershipNameEnabled", "agency_dealership_name", "agencyDealershipName"],
    ["mealPreferenceEnabled", "meal_preference", "mealPreference"],
  ] as const)("enforces %s identically in single and family policy", (enabled, field, value) => {
    const input = fixture(); input.settings[enabled] = true;
    input.settings.uploadConfig.required_fields = { [field]: true };
    expect(validateSingleReview(input)).toBeTruthy();
    expect(validateFamilyReview(input)).toBe("Complete the required group fields for Synthetic 0.");
    input.draft[value] = "Filled"; input.familyMembers.forEach((member) => { member[value] = "Filled"; });
    expect(validateSingleReview(input)).toBeNull();
    expect(validateFamilyReview(input)).toBeNull();
    input.settings.uploadConfig.required_fields = { [field]: false }; input.draft[value] = "";
    expect(validateSingleReview(input)).toBeNull();
  });
  it("requires only enabled custom answers and uses configured field labels", () => {
    const input = fixture();
    input.settings.enabledCustomQuestions = [{ id: "question", label: "Question", enabled: true, required: true, options: ["Yes"] }];
    input.settings.enabledCustomDetails = [{ id: "detail", label: "Detail", enabled: true, required: true }];
    expect(configuredReviewError(input.settings, input.draft)).toContain("custom question");
    input.draft.customAnswers.question = "Yes";
    expect(configuredReviewError(input.settings, input.draft)).toContain("custom detail");
    input.draft.customDetailAnswers.detail = "Filled";
    expect(configuredReviewError(input.settings, input.draft)).toBeNull();
    input.settings.agentEmployeeCodeEnabled = true;
    input.settings.uploadConfig.required_fields = { agent_employee_code: true };
    input.settings.uploadConfig.agent_employee_code_label = "Producer Code";
    expect(configuredReviewError(input.settings, input.draft)).toBe("Please enter your producer code.");
  });
  it("does not require a configured field when its feature is disabled", () => {
    const input = fixture(); input.settings.uploadConfig.required_fields = { staff_code: true };
    expect(validateSingleReview(input)).toBeNull();
  });
  it("rejects malformed contact numbers, short names and missing airport", () => {
    const input = fixture(); input.draft.clientPhone = "broken";
    expect(validateSingleReview(input)).toContain("number");
    input.draft.clientPhone = "+919999999999"; input.draft.clientName = "X";
    expect(validateSingleReview(input)).toContain("full name");
    input.draft.clientName = "Synthetic"; input.settings.airportEnabled = true;
    input.settings.uploadConfig.required_fields = { departure_city: true };
    expect(validateSingleReview(input)).toContain("international airport");
    expect(validateFamilyReview(input)).toContain("family nearest international airport");
  });
  it("blocks absent family documents and incomplete head contact before submission", () => {
    const input = fixture(); input.familyMembers[0].email = "";
    expect(validateFamilyReview(input)).toContain("Head of family");
    input.familyMembers[0].email = "head@example.com";
    input.familyMembers[1].submission = null!;
    expect(validateFamilyReview(input)).toContain("Upload passport for Synthetic 1");
  });
  it("rejects a malformed family number before any API mutation", () => {
    const input = fixture(); input.familyMembers[1].phone = "broken";
    expect(validateFamilyReview(input)).toContain("number");
  });
  it("requires canonical passport details only when there is a passport to review", () => {
    const input = fixture(); input.requiresPassportReview = () => true;
    expect(validateSingleReview(input)).toContain("required passport fields");
    expect(validateFamilyReview(input)).toContain("Fill all passport fields for Synthetic 0");
    input.canReviewSubmission = () => false;
    expect(validateSingleReview(input)).toBeTruthy();
    expect(validateFamilyReview(input)).toContain("Synthetic 0:");
  });
});
