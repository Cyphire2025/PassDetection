import type { ReactNode } from "react";
import { BadgeCheck, Mail, MapPin, Phone, User, Utensils } from "lucide-react";
import { Input } from "@/components/ui/input";
import type {
  CustomUploadDetail,
  CustomUploadQuestion,
} from "@/features/passports/api/upload-links.api";
import type { AgentEmployeeType } from "./upload-flow.types";
import { DEFAULT_UPLOAD_CONFIGURATION, isUploadFieldRequired, type UploadConfiguration } from "@/features/passports/types/upload-configuration";

export function NameInput({
  value,
  onChange,
  placeholder = "e.g. John Doe",
  autoFocus = false,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  return (
    <div className="relative min-w-0">
      <User className="absolute left-4 top-3.5 h-5 w-5 text-slate-400" />
      <Input
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-white pl-12 text-base shadow-sm transition-colors placeholder:text-slate-400 focus-visible:ring-blue-600"
        required
        autoFocus={autoFocus}
      />
    </div>
  );
}

export function SelectInput({
  label,
  value,
  values,
  onChange,
  disabled = false,
}: {
  label: string;
  value: string;
  values: string[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <label className="block min-w-0 space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-base text-slate-900 shadow-sm outline-none transition disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        required
      >
        <option value="">Select {label.toLowerCase()}</option>
        {values.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
    </label>
  );
}

export function ContactInput({
  icon,
  label,
  type,
  value,
  onChange,
  required = false,
  maxLength,
  inputMode,
  pattern,
}: {
  icon: ReactNode;
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  maxLength?: number;
  inputMode?: React.InputHTMLAttributes<HTMLInputElement>["inputMode"];
  pattern?: string;
}) {
  return (
    <label className="block min-w-0 space-y-1.5">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</span>
      <div className="relative min-w-0">
        <span className="absolute left-3 top-3 text-slate-400">{icon}</span>
        <Input
          type={type}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="h-12 w-full min-w-0 rounded-xl border-slate-200 bg-white pl-10 text-base shadow-sm placeholder:text-slate-400 focus-visible:bg-white"
          required={required}
          maxLength={maxLength}
          inputMode={inputMode}
          pattern={pattern}
        />
      </div>
    </label>
  );
}

export function ContactSection({
  email,
  phone,
  departureCity,
  departureCities,
  onEmail,
  onPhone,
  onDepartureCity,
  title,
  emailRequired,
  phoneRequired,
  departureCityRequired = true,
}: {
  email: string;
  phone: string;
  departureCity: string;
  departureCities: string[];
  onEmail: (value: string) => void;
  onPhone: (value: string) => void;
  onDepartureCity: (value: string) => void;
  title: string;
  emailRequired?: boolean;
  phoneRequired?: boolean;
  departureCityRequired?: boolean;
}) {
  return (
    <div className="mt-6 border-t border-slate-100 pt-5">
      <h3 className="mb-3 text-base font-bold text-slate-900">{title}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <ContactInput
          icon={<Mail className="h-5 w-5" />}
          label="Email"
          type="email"
          value={email}
          onChange={onEmail}
          required={emailRequired}
        />
        <ContactInput
          icon={<Phone className="h-5 w-5" />}
          label="WhatsApp active number"
          type="tel"
          value={phone}
          onChange={onPhone}
          required={phoneRequired}
        />
        {departureCities.length > 0 && (
          <DepartureCitySelect
            value={departureCity}
            cities={departureCities}
            onChange={onDepartureCity}
            className="sm:col-span-2"
            required={departureCityRequired}
          />
        )}
      </div>
    </div>
  );
}

export function CustomQuestionFields({
  questions,
  answers,
  onChange,
}: {
  questions: CustomUploadQuestion[];
  answers: Record<string, string>;
  onChange: (questionId: string, value: string) => void;
}) {
  if (questions.length === 0) return null;

  return (
    <div className="mt-5 grid gap-4 rounded-2xl border border-blue-100 bg-blue-50/40 p-4 sm:grid-cols-2">
      {questions.map((question) => (
        <label key={question.id} className="block min-w-0 space-y-1.5">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {question.label}{question.required !== false ? " *" : " (optional)"}
          </span>
          <select
            value={answers[question.id] ?? ""}
            onChange={(event) => onChange(question.id, event.target.value)}
            className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-base text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            required={question.required !== false}
          >
            <option value="">Select an option</option>
            {question.options.map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
      ))}
    </div>
  );
}

export function CustomDetailFields({
  details,
  answers,
  onChange,
}: {
  details: CustomUploadDetail[];
  answers: Record<string, string>;
  onChange: (detailId: string, value: string) => void;
}) {
  if (details.length === 0) return null;

  return (
    <div className="mt-5 grid gap-4 rounded-2xl border border-violet-100 bg-violet-50/40 p-4 sm:grid-cols-2">
      {details.map((detail) => (
        <ContactInput
          key={detail.id}
          icon={<BadgeCheck className="h-5 w-5" />}
          label={detail.label}
          type="text"
          value={answers[detail.id] ?? ""}
          onChange={(value) => onChange(detail.id, value)}
          required={detail.required !== false}
          maxLength={500}
        />
      ))}
    </div>
  );
}

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

export function DepartureCitySelect({
  required = true,
  value,
  cities,
  onChange,
  className = "",
}: {
  value: string;
  cities: string[];
  onChange: (value: string) => void;
  className?: string;
  required?: boolean;
}) {
  return (
    <label className={`block min-w-0 space-y-1.5 ${className}`}>
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">
        Nearest International Airport
      </span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-12 w-full min-w-0 rounded-xl border border-slate-200 bg-white px-3 text-base text-slate-900 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        required={required}
      >
        <option value="">Select your nearest international airport</option>
        {cities.map((city) => <option key={city} value={city}>{city}</option>)}
      </select>
    </label>
  );
}
