import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DEFAULT_UPLOAD_CONFIGURATION } from "@/features/passports/types/upload-configuration";
import { ConfiguredClientFields, CustomDetailFields, CustomQuestionFields, DepartureCitySelect } from "./upload-flow-fields";

describe("current configured traveller fields", () => {
  it("uses edited field labels, accepts alphanumeric codes and enforces each required setting independently", () => {
    render(<form><ConfiguredClientFields config={{ ...DEFAULT_UPLOAD_CONFIGURATION, agent_employee_code_label: "Producer Code", agency_dealership_name_label: "Branch Name", required_fields: { staff_code: true, agent_employee_code: false, agency_dealership_name: false } }} baseCityEnabled={false} askNearestDomesticAirport={false} staffCodeEnabled agentEmployeeCodeEnabled designationEnabled={false} agencyDealershipNameEnabled mealPreferenceEnabled={false} baseCity="" nearestDomesticAirport="" staffCode="" agentEmployeeType="" agentEmployeeCode="A-42" designation="" agencyDealershipName="" mealPreference="" onBaseCity={() => {}} onNearestDomesticAirport={() => {}} onStaffCode={() => {}} onAgentEmployeeType={() => {}} onAgentEmployeeCode={() => {}} onDesignation={() => {}} onAgencyDealershipName={() => {}} onMealPreference={() => {}} />
      <CustomQuestionFields questions={[{ id: "q1", label: "Required question", enabled: true, required: true, options: ["Yes"] }, { id: "q2", label: "Optional question", enabled: true, required: false, options: ["Yes"] }]} answers={{}} onChange={() => {}} />
      <CustomDetailFields details={[{ id: "d1", label: "Optional detail", enabled: true, required: false }]} answers={{}} onChange={() => {}} />
      <DepartureCitySelect value="" cities={["Delhi"]} onChange={() => {}} required={false} />
    </form>);
    expect(screen.queryByLabelText("Agent or Employee")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Producer Code")).toHaveValue("A-42");
    expect(screen.getByLabelText("Producer Code")).not.toBeRequired();
    expect(screen.getByLabelText("Branch Name")).not.toBeRequired();
    expect(screen.getByLabelText("Staff Code")).toBeRequired();
    expect(screen.getByLabelText("Required question *")).toBeRequired();
    expect(screen.getByLabelText("Optional question (optional)")).not.toBeRequired();
    expect(screen.getByLabelText("Optional detail")).not.toBeRequired();
    expect(screen.getByLabelText("Nearest International Airport")).not.toBeRequired();
  });

});
