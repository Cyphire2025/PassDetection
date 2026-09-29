"use client";
import {
  WorkspaceSummaryItem,
  WorkspaceSummaryStrip,
} from "@/components/shared/workspace-ui";
import { Button, Card, CardContent, Skeleton } from "@/components/ui";
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  Pencil,
  UsersRound,
  X,
} from "lucide-react";
import { DEFAULT_TRIP_TIMEZONE } from "../utils/trip-timezone";
import { formatPassportDateForUi } from "@/lib/utils/passport-date";
import { getImportOnlySettings } from "../schemas/upload-link.schema";
import { DEFAULT_UPLOAD_CONFIGURATION, isUploadFieldRequired, type RequiredUploadField, type UploadConfiguration } from "../types/upload-configuration";
import {
  GroupDocumentDeliveryPanel,
  GroupWhatsAppBroadcastPanel,
} from "./passport-group-bindings";
import { InfoPair } from "./passport-group-model";
import type { PassportGroupController } from "./use-passport-group-controller";
export function PassportGroupOverviewPanel({
  isLoading,
  groupDetails,
  submissionsView,
  isTripDetailsExpanded,
  tripDetailsRegionId,
  setIsTripDetailsExpanded,
  setTripForm,
  setIsEditingTrip,
  error,
  groupId,
  includeDeleted,
  canAccessWhatsApp,
  importMessage,
  bulkDeleteFeedback,
}: Pick<
  PassportGroupController,
  | "isLoading"
  | "groupDetails"
  | "submissionsView"
  | "isTripDetailsExpanded"
  | "tripDetailsRegionId"
  | "setIsTripDetailsExpanded"
  | "setTripForm"
  | "setIsEditingTrip"
  | "error"
  | "groupId"
  | "includeDeleted"
  | "canAccessWhatsApp"
  | "importMessage"
  | "bulkDeleteFeedback"
>) {
  const configuration = { ...DEFAULT_UPLOAD_CONFIGURATION, ...groupDetails?.upload_configuration };
  const airportEnabled = Boolean(groupDetails?.nearest_international_airport_enabled)
    || (groupDetails?.upload_configuration == null && (groupDetails?.departure_cities?.length ?? 0) > 0);
  return (
    <>
      <WorkspaceSummaryStrip label="Group passport readiness">
        {isLoading && !groupDetails ? (
          Array.from({ length: 4 }).map((_, index) => (
            <Skeleton key={index} className="h-[72px] rounded-none" />
          ))
        ) : (
          <>
            <WorkspaceSummaryItem
              label="Submitted"
              value={(
                submissionsView?.group_total ??
                groupDetails?.total_passports ??
                0
              ).toLocaleString()}
              helper="passengers"
              icon={UsersRound}
              tone="info"
            />
            <WorkspaceSummaryItem
              label="Needs review"
              value={(groupDetails?.pending_review_count ?? 0).toLocaleString()}
              helper="records"
              icon={AlertTriangle}
              tone={
                (groupDetails?.pending_review_count ?? 0) > 0
                  ? "attention"
                  : "success"
              }
            />
            <WorkspaceSummaryItem
              label="Confirmed"
              value={(groupDetails?.confirmed_count ?? 0).toLocaleString()}
              helper="ready"
              icon={CheckCircle2}
              tone="success"
            />
            <WorkspaceSummaryItem
              label="Failed"
              value={(groupDetails?.failed_count ?? 0).toLocaleString()}
              helper="need recovery"
              icon={X}
              tone={
                (groupDetails?.failed_count ?? 0) > 0 ? "attention" : "default"
              }
            />
          </>
        )}
      </WorkspaceSummaryStrip>
      {groupDetails && (
        <section aria-label="Group overview" className="space-y-3">
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,17rem),1fr))] items-stretch gap-3">
          <Card className="h-full min-w-0">
            <CardContent className="flex h-full min-h-52 flex-col gap-3 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                    <CalendarDays className="h-4 w-4" aria-hidden="true" />
                  </span>
                  <div>
                    <h2 className="text-sm font-semibold text-slate-900">
                      Trip details
                    </h2>
                  </div>
                </div>
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-base font-semibold text-slate-900" title={groupDetails.destination || undefined}>{groupDetails.destination || "Destination not set"}</p>
                <p className="mt-1 text-sm text-slate-600">
                  {formatPassportDateForUi(groupDetails.travel_date) || "Departure not set"}
                  {groupDetails.return_date && ` – ${formatPassportDateForUi(groupDetails.return_date)}`}
                </p>
                <p className="mt-1 truncate text-xs text-slate-500">{groupDetails.timezone || DEFAULT_TRIP_TIMEZONE}</p>
              </div>
                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 pt-3">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-expanded={isTripDetailsExpanded}
                    aria-controls={tripDetailsRegionId}
                    onClick={() =>
                      setIsTripDetailsExpanded((current) => !current)
                    }
                  >
                    <ChevronDown
                      className={`h-4 w-4 transition-transform ${isTripDetailsExpanded ? "rotate-180" : ""}`}
                      aria-hidden="true"
                    />
                    {isTripDetailsExpanded ? "Hide details" : "Show details"}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setTripForm({
                        import_only: groupDetails.import_only,
                        upload_configuration: groupDetails.upload_configuration ?? undefined,
                        custom_questions: groupDetails.custom_questions,
                        custom_details: groupDetails.custom_details,
                        name: groupDetails.group_name,
                        destination: groupDetails.destination ?? "",
                        travel_date: groupDetails.travel_date ?? "",
                        return_date: groupDetails.return_date ?? "",
                        timezone:
                          groupDetails.timezone ?? DEFAULT_TRIP_TIMEZONE,
                        departure_cities: groupDetails.departure_cities ?? [],
                        base_city_enabled: groupDetails.base_city_enabled,
                        nearest_international_airport_enabled:
                          airportEnabled,
                        staff_code_enabled: groupDetails.staff_code_enabled,
                        agent_employee_code_enabled:
                          groupDetails.agent_employee_code_enabled,
                        meal_preference_enabled:
                          groupDetails.meal_preference_enabled,
                        require_selfie: groupDetails.require_selfie,
                        allow_files_from_device:
                          groupDetails.allow_files_from_device ?? true,
                        ask_nearest_domestic_airport:
                          groupDetails.ask_nearest_domestic_airport ?? false,
                        relation_with_qualifier_enabled:
                          groupDetails.relation_with_qualifier_enabled ?? false,
                        designation_enabled:
                          groupDetails.designation_enabled ?? false,
                        agency_dealership_name_enabled:
                          groupDetails.agency_dealership_name_enabled ?? false,
                        notes: groupDetails.notes ?? "",
                        ...(groupDetails.import_only ? getImportOnlySettings() : {}),
                      });
                      setIsEditingTrip(true);
                    }}
                  >
                    <Pencil className="h-4 w-4" aria-hidden="true" />
                    Edit
                  </Button>
                </div>
            </CardContent>
          </Card>
          {!includeDeleted && !error && (
            <>
              {canAccessWhatsApp && !groupDetails.import_only && (
                <GroupWhatsAppBroadcastPanel groupId={groupId} />
              )}
              <GroupDocumentDeliveryPanel groupId={groupId} />
            </>
          )}
          </div>
          {isTripDetailsExpanded && (
                <div
                  id={tripDetailsRegionId}
                  role="region"
                  aria-label="Destination and trip details"
                  className="grid gap-4 rounded-xl border border-slate-200 bg-white p-4 text-sm sm:grid-cols-2 lg:grid-cols-3"
                >
                  <InfoPair
                    label="Destination"
                    value={groupDetails.destination || "Not set"}
                  />
                  <InfoPair
                    label="Travel/Departure Date"
                    value={groupDetails.travel_date || "Not set"}
                  />
                  <InfoPair
                    label="Return Date"
                    value={groupDetails.return_date || "Not set"}
                  />
                  <InfoPair
                    label="Trip Timezone"
                    value={groupDetails.timezone || DEFAULT_TRIP_TIMEZONE}
                  />
                  {!groupDetails.import_only && <>
                  <InfoPair
                    label="Base City"
                    value={fieldRequirement(configuration, groupDetails.base_city_enabled, "base_city")}
                  />
                  <InfoPair
                    label="Nearest International Airport"
                    value={
                      airportEnabled
                        ? (groupDetails.departure_cities ?? []).join(", ") ||
                          "Not configured"
                        : "Disabled"
                    }
                  />
                  <InfoPair
                    label="Staff Code"
                    value={fieldRequirement(configuration, groupDetails.staff_code_enabled, "staff_code")}
                  />
                  <InfoPair
                    label={configuration.agent_employee_code_label}
                    value={fieldRequirement(configuration, groupDetails.agent_employee_code_enabled, "agent_employee_code")}
                  />
                  <InfoPair
                    label="Meal Preference"
                    value={fieldRequirement(configuration, groupDetails.meal_preference_enabled, "meal_preference")}
                  />
                  <InfoPair
                    label="Visa Photo"
                    value={requirementText(groupDetails.require_selfie, configuration.visa_photo_required)}
                  />
                  <InfoPair
                    label="Passport"
                    value={requirementText(configuration.passport_enabled, configuration.passport_required)}
                  />
                  <InfoPair
                    label="Passport Collection"
                    value={passportMethods(configuration, groupDetails.allow_files_from_device ?? true)}
                  />
                  <InfoPair
                    label="Nearest Domestic Airport"
                    value={fieldRequirement(configuration, groupDetails.ask_nearest_domestic_airport, "nearest_domestic_airport")}
                  />
                  <InfoPair
                    label="Relation with Qualifier"
                    value={fieldRequirement(configuration, groupDetails.relation_with_qualifier_enabled, "relation_with_qualifier")}
                  />
                  {groupDetails.relation_with_qualifier_enabled && (
                    <InfoPair
                      label="Relationship Options"
                      value={[
                        configuration.qualifier_relation_list_enabled && "Choose from list",
                        configuration.qualifier_relation_other_enabled && "Other relationship",
                      ].filter(Boolean).join(" and ") || "No options enabled"}
                    />
                  )}
                  <InfoPair
                    label="Designation"
                    value={fieldRequirement(configuration, groupDetails.designation_enabled, "designation")}
                  />
                  <InfoPair
                    label={configuration.agency_dealership_name_label}
                    value={fieldRequirement(configuration, groupDetails.agency_dealership_name_enabled, "agency_dealership_name")}
                  />
                  <div className="sm:col-span-2">
                    <InfoPair
                      label="Notes"
                      value={groupDetails.notes || "No notes"}
                    />
                  </div>
                  </>}
                </div>
              )}
        </section>
      )}
      {importMessage && (
        <div
          role="status"
          aria-live="polite"
          className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800"
        >
          {importMessage}
        </div>
      )}
      {bulkDeleteFeedback && (
        <div
          role={bulkDeleteFeedback.tone === "error" ? "alert" : "status"}
          className={
            bulkDeleteFeedback.tone === "error"
              ? "rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
              : bulkDeleteFeedback.tone === "warning"
                ? "rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
                : "rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
          }
        >
          {bulkDeleteFeedback.message}
        </div>
      )}
    </>
  );
}

function requirementText(enabled: boolean | undefined, required: boolean) {
  return enabled ? (required ? "Required" : "Optional") : "Disabled";
}

function fieldRequirement(configuration: UploadConfiguration, enabled: boolean | undefined, field: RequiredUploadField) {
  return requirementText(enabled, isUploadFieldRequired(configuration, field));
}

function passportMethods(configuration: UploadConfiguration, fileUpload: boolean) {
  if (!configuration.passport_enabled) return "Disabled";
  return [configuration.passport_live_scan && "Live scan", fileUpload && "Document upload"].filter(Boolean).join(" and ") || "No methods enabled";
}
