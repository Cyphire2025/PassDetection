"use client";
import type { FreshDraftState } from "../hooks/use-fresh-draft";
import type { getUploadFlowSettings } from "../services/configured-upload";
import { ConfiguredClientFields, CustomDetailFields, CustomQuestionFields, DepartureCitySelect, SelectInput } from "./upload-flow-fields";
import { FAMILY_RELATIONS, GENDERS } from "./upload-flow.constants";
import { isUploadFieldRequired } from "@/features/passports/types/upload-configuration";

export function FreshTripFields({ state, settings, memberIndex }: { state: FreshDraftState; settings: ReturnType<typeof getUploadFlowSettings>; memberIndex: number }) {
  const details = state.payload!.current_details;
  const set = (key: string) => (value: string) => state.update("current_details", key, value);
  return <>
    {state.payload?.collection?.submission_mode === "family" && <div className="mt-5 grid gap-4 sm:grid-cols-2"><SelectInput label="Relationship" value={state.payload.collection.family_relation ?? ""} values={memberIndex === 0 ? ["Head"] : FAMILY_RELATIONS.filter((item) => item !== "Head")} disabled={memberIndex === 0} onChange={(family_relation) => state.collection({ family_relation })} /><SelectInput label="Gender" value={state.payload.collection.family_gender ?? ""} values={GENDERS} onChange={(family_gender) => state.collection({ family_gender })} /></div>}
    {settings.airportEnabled && <div className="mt-5"><DepartureCitySelect value={details.departure_city ?? ""} cities={settings.departureCities} onChange={set("departure_city")} required={isUploadFieldRequired(settings.uploadConfig, "departure_city")} /></div>}
    <ConfiguredClientFields config={settings.uploadConfig} baseCityEnabled={settings.baseCityEnabled} askNearestDomesticAirport={settings.askNearestDomesticAirport} staffCodeEnabled={settings.staffCodeEnabled} agentEmployeeCodeEnabled={settings.agentEmployeeCodeEnabled} designationEnabled={settings.designationEnabled} agencyDealershipNameEnabled={settings.agencyDealershipNameEnabled} mealPreferenceEnabled={settings.mealPreferenceEnabled}
      baseCity={details.base_city ?? ""} nearestDomesticAirport={details.nearest_domestic_airport ?? ""} staffCode={details.staff_code ?? ""} agentEmployeeType="agent" agentEmployeeCode={details.agent_employee_code ?? ""} designation={details.designation ?? ""} agencyDealershipName={details.agency_dealership_name ?? ""} mealPreference={details.meal_preference ?? ""}
      onBaseCity={set("base_city")} onNearestDomesticAirport={set("nearest_domestic_airport")} onStaffCode={set("staff_code")} onAgentEmployeeType={() => undefined} onAgentEmployeeCode={set("agent_employee_code")} onDesignation={set("designation")} onAgencyDealershipName={set("agency_dealership_name")} onMealPreference={set("meal_preference")} />
    <CustomQuestionFields questions={settings.enabledCustomQuestions} answers={state.payload!.custom_answers} onChange={(key, value) => state.update("custom_answers", key, value)} />
    <CustomDetailFields details={settings.enabledCustomDetails} answers={state.payload!.custom_detail_answers} onChange={(key, value) => state.update("custom_detail_answers", key, value)} />
  </>;
}
