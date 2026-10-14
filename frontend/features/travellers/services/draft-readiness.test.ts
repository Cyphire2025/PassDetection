import { describe, expect, it } from "vitest";
import { draftReviewReadiness } from "./draft-readiness";
import type { ReturningDraft } from "../api/draft.types";
import type { ReturningHistory } from "../types";

const history = { contact_phone: "+919999999999", suitability: { outcome: "review_required" }, group_requirements: { require_contact_phone: false }, missing_requirements: [] } as unknown as ReturningHistory;
const draft: ReturningDraft = { id: "private", revision: 3, expires_at: "2099-01-01", status: "active", verified_phone: null, documents: [{ id: "back", side: "back", state: "ready" }], extraction_status: "none", extracted_fields: {}, passport_fields: {}, current_details: {}, custom_answers: {}, custom_detail_answers: {} };
describe("returning temporary ECR readiness", () => {
  it("requires new front evidence when resumed text changes the saved passport number", () => {
    const previous = { ...history, extracted_fields: { passport_number: "A123456" } };
    const changed = { ...draft, passport_fields: { passport_number: "B123456" } };
    expect(draftReviewReadiness(previous, changed, false, true)).toMatchObject({ needsReplacement: true, canSubmit: false });
    const withFront = { ...changed, documents: [...changed.documents, { id: "new-front", side: "front" as const, state: "ready" as const }], extraction_status: "succeeded" as const };
    expect(draftReviewReadiness(previous, withFront, false, true)).toMatchObject({ needsReplacement: false, canSubmit: true });
  });
  it("allows formatting corrections to the same saved passport without new images", () => {
    const previous = { ...history, extracted_fields: { passport_number: "A123456" } };
    const same = { ...draft, passport_fields: { passport_number: "ａ 123-456" } };
    expect(draftReviewReadiness(previous, same, false, true)).toMatchObject({ needsReplacement: false, canSubmit: true });
  });
  it.each(["pending", "running", "failed"] as const)("does not submit a ready back image with %s ECR", (ecr_status) => {
    const readiness = draftReviewReadiness(history, { ...draft, ecr_status }, false, true);
    expect(readiness.canSubmit).toBe(false); expect(readiness.extracting).toBe(ecr_status !== "failed");
  });
  it("retains an explicit REVIEW result when the check completed", () => {
    const value = { ...draft, ecr_status: "succeeded" as const, ecr_result: "REVIEW" as const };
    expect(draftReviewReadiness(history, value, false, true).canSubmit).toBe(true); expect(value.ecr_result).toBe("REVIEW");
  });
});
