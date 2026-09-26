import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { getUploadFlowSettings } from "../services/configured-upload";
import { createFamilyMembers } from "../services/upload-flow-helpers";
import { UploadFamilyReview, UploadSingleReview } from "./upload-review-panels";

vi.mock("./protected-upload-document-image", () => ({ ProtectedUploadDocumentImage: ({ alt }: { alt: string }) => <span>{alt}</span> }));
type FamilyProps = ComponentProps<typeof UploadFamilyReview>;
type SingleProps = ComponentProps<typeof UploadSingleReview>;
const saved = { id: "saved", image_s3_key: "", status: "ready_for_client_review" } as PassportSubmission;
function familyProps(): FamilyProps {
  const settings = getUploadFlowSettings();
  Object.assign(settings, { baseCityEnabled: true, askNearestDomesticAirport: true, staffCodeEnabled: true, agentEmployeeCodeEnabled: true,
    designationEnabled: true, agencyDealershipNameEnabled: true, mealPreferenceEnabled: true, airportEnabled: true, departureCities: ["Delhi"],
    enabledCustomQuestions: [{ id: "question", label: "Transport", enabled: true, options: ["Bus"] }],
    enabledCustomDetails: [{ id: "detail", label: "Reference", enabled: true }] });
  return { token: "token", settings, documents: { extractingSubmissionId: null, handleScanAgain: vi.fn(), handleFamilyScanAgain: vi.fn(), replaceSavedPassport: vi.fn(), isScanningAgain: false, isReplacingSavedPassport: false },
    contactVerification: { edit: vi.fn() }, canReviewSubmission: () => true, uploadError: null, departureCity: "", setDepartureCity: vi.fn(), onSubmit: vi.fn(async (event) => { event.preventDefault(); }),
    familyMembers: createFamilyMembers(2).map((member, index) => ({ ...member, name: `Member ${index}`, email: `member${index}@example.com`, phone: "+919999999999", submission: { ...saved, id: `saved-${index}` }, customAnswers: { retained: "Existing" }, customDetailAnswers: { retained: "Existing" } })),
    hasBlockedFamilyVerification: false, setStep: vi.fn(), selectFamilyMember: vi.fn(), updateFamilyMember: vi.fn(), handleFamilyReviewFieldChange: vi.fn() };
}
function singleProps(): SingleProps {
  const shared = familyProps();
  const review = { clientName: "Synthetic", clientEmail: "synthetic@example.com", clientPhone: "+919999999999", reviewFields: {}, departureCity: "", baseCity: "", nearestDomesticAirport: "", staffCode: "", agentEmployeeCode: "", designation: "", agencyDealershipName: "", mealPreference: "", customAnswers: {}, customDetailAnswers: {} };
  return { ...shared, submission: saved, singleUploadIdempotencyKey: "key", review, requiresPassportReview: () => false,
    extractionNotice: null, canRetryExtraction: true, setClientName: vi.fn(), handleReviewFieldChange: vi.fn(), setCustomAnswers: vi.fn(), setCustomDetailAnswers: vi.fn(),
    configuredFields: { ...shared.settings, config: shared.settings.uploadConfig, ...review, agentEmployeeType: "",
      onBaseCity: vi.fn(), onNearestDomesticAirport: vi.fn(), onStaffCode: vi.fn(), onAgentEmployeeType: vi.fn(), onAgentEmployeeCode: vi.fn(), onDesignation: vi.fn(), onAgencyDealershipName: vi.fn(), onMealPreference: vi.fn() } };
}

describe("review rendering boundaries", () => {
  it("keeps family configured edits scoped to the selected member and preserves other custom answers", () => {
    const input = familyProps(); render(<UploadFamilyReview {...input} />);
    const second = within(screen.getAllByRole("group")[1]);
    for (const [label, field] of [["Base City", "baseCity"], ["Nearest Domestic Airport", "nearestDomesticAirport"], ["Staff Code", "staffCode"], [input.settings.uploadConfig.agent_employee_code_label, "agentEmployeeCode"], ["Designation", "designation"], [input.settings.uploadConfig.agency_dealership_name_label, "agencyDealershipName"]]) {
      fireEvent.change(second.getByLabelText(label), { target: { value: "Updated" } });
      expect(input.updateFamilyMember).toHaveBeenLastCalledWith(1, { [field]: "Updated" });
    }
    fireEvent.change(second.getByLabelText("Meal Preference"), { target: { value: "Veg" } });
    expect(input.updateFamilyMember).toHaveBeenLastCalledWith(1, { mealPreference: "Veg" });
    fireEvent.change(second.getByLabelText(/Transport/), { target: { value: "Bus" } });
    expect(input.updateFamilyMember).toHaveBeenLastCalledWith(1, { customAnswers: { retained: "Existing", question: "Bus" } });
    fireEvent.change(second.getByLabelText("Reference"), { target: { value: "Booking" } });
    expect(input.updateFamilyMember).toHaveBeenLastCalledWith(1, { customDetailAnswers: { retained: "Existing", detail: "Booking" } });
    fireEvent.change(second.getByLabelText(/Full name/), { target: { value: "Corrected" } });
    expect(input.updateFamilyMember).toHaveBeenLastCalledWith(1, { name: "Corrected" });
    expect(input.handleFamilyReviewFieldChange).toHaveBeenLastCalledWith(1, "given_names", "Corrected");
    fireEvent.click(second.getByRole("button", { name: "Change contact details" }));
    expect(input.contactVerification.edit).toHaveBeenCalledWith("saved-1");
    fireEvent.click(second.getByRole("button", { name: "Review document options" }));
    expect(input.selectFamilyMember).toHaveBeenCalledWith(1); expect(input.setStep).toHaveBeenCalledWith("METHOD_SELECT");
    fireEvent.click(screen.getByRole("button", { name: "Back to uploads" }));
    expect(input.setStep).toHaveBeenCalledWith("METHOD_SELECT");
  });
  it("locks a completed family member while allowing the pending member's saved-image retry", () => {
    const input = familyProps();
    input.familyMembers[0].submission = { ...saved, status: "submitted" };
    input.familyMembers[1].canRetryExtraction = true;
    input.familyMembers[1].submission = { ...saved, image_s3_key: "synthetic.jpg" };
    render(<UploadFamilyReview {...input} />);
    expect(screen.getAllByRole("group")[0]).toBeDisabled();
    const second = within(screen.getAllByRole("group")[1]);
    fireEvent.change(second.getByLabelText("Surname"), { target: { value: "Corrected" } });
    expect(input.handleFamilyReviewFieldChange).toHaveBeenCalledWith(1, "surname", "Corrected");
    fireEvent.click(second.getByRole("button", { name: "Retry reading saved image" }));
    expect(input.documents.handleFamilyScanAgain).toHaveBeenCalledWith(1);
    expect(screen.getByRole("button", { name: "Submit Family Details" })).toBeEnabled();
  });
  it.each(["retry", "replace"] as const)("blocks unverified single and family submissions and routes %s to the correct saved object", (action) => {
    const single = singleProps(); single.canReviewSubmission = () => false;
    single.requiresPassportReview = () => true;
    single.submission = { ...saved, extracted_fields: { ai_verification: { available: true, status: action === "replace" ? "wrong_document" : "pending" } } } as PassportSubmission;
    const rendered = render(<UploadSingleReview {...single} />);
    const label = action === "replace" ? "Replace passport pages" : "Retry verification on saved image";
    fireEvent.click(screen.getByRole("button", { name: label }));
    expect(action === "replace" ? single.documents.replaceSavedPassport : single.documents.handleScanAgain).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Submit/ })).not.toBeInTheDocument();
    rendered.unmount();
    const family = familyProps(); family.hasBlockedFamilyVerification = true; family.canReviewSubmission = () => false;
    family.familyMembers[0].submission = single.submission; family.familyMembers[1].submission = null;
    render(<UploadFamilyReview {...family} />);
    fireEvent.click(screen.getByRole("button", { name: label }));
    expect(action === "replace" ? family.documents.replaceSavedPassport : family.documents.handleFamilyScanAgain).toHaveBeenCalledWith(0);
    expect(screen.queryByRole("button", { name: /Submit Family/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Complete this member's document step before reviewing/)).toBeVisible();
  });
  it("keeps single custom answers and contact edits connected after the rendering extraction", () => {
    const input = singleProps(); render(<UploadSingleReview {...input} />);
    fireEvent.change(screen.getByLabelText(/Full name/), { target: { value: "Corrected" } });
    expect(input.setClientName).toHaveBeenCalledWith("Corrected");
    expect(input.handleReviewFieldChange).toHaveBeenCalledWith("given_names", "Corrected");
    fireEvent.change(screen.getByLabelText(/Transport/), { target: { value: "Bus" } });
    const update = vi.mocked(input.setCustomAnswers).mock.calls[0][0];
    expect(typeof update === "function" && update({ retained: "Existing" })).toEqual({ retained: "Existing", question: "Bus" });
    fireEvent.change(screen.getByLabelText("Reference"), { target: { value: "Booking" } });
    const detailUpdate = vi.mocked(input.setCustomDetailAnswers).mock.calls[0][0];
    expect(typeof detailUpdate === "function" && detailUpdate({ retained: "Existing" })).toEqual({ retained: "Existing", detail: "Booking" });
    fireEvent.click(screen.getByRole("button", { name: "Change contact details" }));
    expect(input.contactVerification.edit).toHaveBeenCalledWith(saved.id);
    fireEvent.click(screen.getByRole("button", { name: "Retry automatic reading" }));
    expect(input.documents.handleScanAgain).toHaveBeenCalled();
  });
});
