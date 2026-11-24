import { BadgeCheck, MapPin, Utensils } from "lucide-react";
import { DEFAULT_UPLOAD_CONFIGURATION, isUploadFieldRequired, type UploadConfiguration } from "@/features/passports/types/upload-configuration";
import type { AgentEmployeeType } from "./upload-flow.types";
import { ContactInput } from "./upload-contact-input";

export function ConfiguredClientFields({
  config = DEFAULT_UPLOAD_CONFIGURATION,
  baseCityEnabled,
  askNearestDomesticAirport,
  staffCodeEnabled,
  agentEmployeeCodeEnabled,
  designationEnabled,
  agencyDealershipNameEnabled,
  mealPreferenceEnabled,
  baseCity,
  nearestDomesticAirport,
  staffCode,
  agentEmployeeCode,
  designation,
  agencyDealershipName,
  mealPreference,
  onBaseCity,
  onNearestDomesticAirport,
  onStaffCode,
  onAgentEmployeeCode,
  onDesignation,
  onAgencyDealershipName,
  onMealPreference,
}: {
  config?: UploadConfiguration;
  baseCityEnabled: boolean;
  askNearestDomesticAirport: boolean;
  staffCodeEnabled: boolean;
  agentEmployeeCodeEnabled: boolean;
  designationEnabled: boolean;
  agencyDealershipNameEnabled: boolean;
  mealPreferenceEnabled: boolean;
  baseCity: string;
  nearestDomesticAirport: string;
  staffCode: string;
  agentEmployeeType: AgentEmployeeType;
  agentEmployeeCode: string;
  designation: string;
  agencyDealershipName: string;
  mealPreference: string;
  onBaseCity: (value: string) => void;
  onNearestDomesticAirport: (value: string) => void;
  onStaffCode: (value: string) => void;
  onAgentEmployeeType: (value: AgentEmployeeType) => void;
  onAgentEmployeeCode: (value: string) => void;
  onDesignation: (value: string) => void;
  onAgencyDealershipName: (value: string) => void;
  onMealPreference: (value: string) => void;
}) {
  if (
    !baseCityEnabled
    && !askNearestDomesticAirport
    && !staffCodeEnabled
    && !agentEmployeeCodeEnabled
    && !designationEnabled
    && !agencyDealershipNameEnabled
    && !mealPreferenceEnabled
  ) return null;

  return (
    <div className="mt-5 grid gap-4 rounded-2xl border border-slate-100 bg-slate-50 p-4 sm:grid-cols-2">
      {baseCityEnabled && (
        <ContactInput
          icon={<MapPin className="h-5 w-5" />}
          label="Base City"
          type="text"
          value={baseCity}
          onChange={onBaseCity}
          required={isUploadFieldRequired(config, "base_city")}
        />
      )}
      {askNearestDomesticAirport && (
        <ContactInput
          icon={<MapPin className="h-5 w-5" />}
          label="Nearest Domestic Airport"
          type="text"
          value={nearestDomesticAirport}
          onChange={onNearestDomesticAirport}
          required={isUploadFieldRequired(config, "nearest_domestic_airport")}
          maxLength={120}
        />
      )}
      {staffCodeEnabled && (
        <ContactInput
          icon={<BadgeCheck className="h-5 w-5" />}
          label="Staff Code"
          type="text"
          value={staffCode}
          onChange={onStaffCode}
          required={isUploadFieldRequired(config, "staff_code")}
        />
      )}
      {agentEmployeeCodeEnabled && (
          <ContactInput
            icon={<BadgeCheck className="h-5 w-5" />}
            label={config.agent_employee_code_label}
            type="text"
            value={agentEmployeeCode}
            onChange={onAgentEmployeeCode}
            required={isUploadFieldRequired(config, "agent_employee_code")}
            maxLength={80}
          />
      )}
      {designationEnabled && (
        <ContactInput
          icon={<BadgeCheck className="h-5 w-5" />}
          label="Designation"
          type="text"
          value={designation}
          onChange={onDesignation}
          required={isUploadFieldRequired(config, "designation")}
          maxLength={160}
        />
      )}
      {agencyDealershipNameEnabled && (
        <ContactInput
          icon={<BadgeCheck className="h-5 w-5" />}
          label={config.agency_dealership_name_label}
          type="text"
          value={agencyDealershipName}
          onChange={onAgencyDealershipName}
          required={isUploadFieldRequired(config, "agency_dealership_name")}
          maxLength={200}
        />
      )}
      {mealPreferenceEnabled && (
        <label className="block min-w-0 space-y-1.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Meal Preference
          </span>
          <div className="relative min-w-0">
            <Utensils className="absolute left-3 top-3.5 h-5 w-5 text-slate-400" />
            <select
              value={mealPreference}
              onChange={(event) => onMealPreference(event.target.value)}
              className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-base text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              required={isUploadFieldRequired(config, "meal_preference")}
            >
              <option value="">Select meal preference</option>
              <option value="Veg">Veg</option>
              <option value="Non Veg">Non Veg</option>
              <option value="Jain">Jain</option>
            </select>
          </div>
        </label>
      )}
    </div>
  );
}
