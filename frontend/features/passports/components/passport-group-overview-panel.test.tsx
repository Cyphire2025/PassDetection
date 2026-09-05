import { useState, type ComponentProps } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PassportGroupSummary } from "@/types/passport.types";
import { DEFAULT_UPLOAD_CONFIGURATION } from "../types/upload-configuration";
import { PassportGroupOverviewPanel } from "./passport-group-overview-panel";
import { TripDetailsDialog, type TripDetailsForm } from "./passport-trip-details-dialog";

vi.mock("./passport-group-bindings", () => ({
  GroupDocumentDeliveryPanel: () => null,
  GroupWhatsAppBroadcastPanel: () => null,
}));

const group: PassportGroupSummary = {
  group_id: "trip", group_name: "Legacy Group", group_status: "active",
  total_passports: 12, pending_review_count: 1, confirmed_count: 11, failed_count: 0,
  latest_submission_at: "2026-09-05T00:00:00Z", destination: "Dubai",
  travel_date: "2026-11-01", return_date: "2026-11-08", timezone: "Asia/Kolkata", package_name: null,
  departure_cities: ["Delhi", "Mumbai"], nearest_international_airport_enabled: false,
  base_city_enabled: true, staff_code_enabled: true, agent_employee_code_enabled: true,
  meal_preference_enabled: true, require_selfie: true, allow_files_from_device: true,
  ask_nearest_domestic_airport: true, relation_with_qualifier_enabled: true,
  designation_enabled: true, agency_dealership_name_enabled: true, notes: null,
  custom_questions: [{ id: "55789cf1-e055-4cda-86c2-7c8d79d52072", label: "Excursion", enabled: true, required: false, options: ["Museum", "Beach"] }],
  custom_details: [{ id: "2823dd2e-b35e-4861-bc30-7f7b9d57d49b", label: "Membership", enabled: true, required: false }],
};

function overviewProps(groupDetails: PassportGroupSummary): ComponentProps<typeof PassportGroupOverviewPanel> {
  return {
    isLoading: false, groupDetails, submissionsView: undefined,
    isTripDetailsExpanded: true, tripDetailsRegionId: "trip-details",
    setIsTripDetailsExpanded: vi.fn(), setTripForm: vi.fn(), setIsEditingTrip: vi.fn(),
    error: null, groupId: groupDetails.group_id,
    includeDeleted: false, canAccessWhatsApp: false, importMessage: null, bulkDeleteFeedback: null,
  };
}

function OverviewEditorHarness({ source, onSave }: { source: PassportGroupSummary; onSave: (form: TripDetailsForm) => void }) {
  const [form, setForm] = useState<TripDetailsForm | null>(null);
  if (form) {
    return <TripDetailsDialog form={form} isLoading={false} onChange={setForm} onClose={() => setForm(null)} onSave={() => onSave(form)} />;
  }
  return <PassportGroupOverviewPanel {...overviewProps(source)} setTripForm={(next) => {
    if (typeof next !== "function") setForm(next);
  }} />;
}

describe("trip settings summary and editor", () => {
  it.each([undefined, null])("preserves legacy airport and custom settings through an unchanged edit for configuration %s", (upload_configuration) => {
    const onSave = vi.fn();
    render(<OverviewEditorHarness source={{ ...group, upload_configuration }} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("switch", { name: "Disable Nearest International Airport" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Make Excursion compulsory" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Make Membership compulsory" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Save Details" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      nearest_international_airport_enabled: true,
      departure_cities: ["Delhi", "Mumbai"],
      custom_questions: group.custom_questions,
      custom_details: group.custom_details,
    }));
  });

  it("allows legacy airport collection to be explicitly disabled without the saved list re-enabling it", () => {
    const onSave = vi.fn();
    render(<OverviewEditorHarness source={{ ...group, upload_configuration: null }} onSave={onSave} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("switch", { name: "Disable Nearest International Airport" }));
    expect(screen.getByRole("switch", { name: "Enable Nearest International Airport" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Save Details" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      nearest_international_airport_enabled: false,
      upload_configuration: expect.objectContaining({ passport_enabled: true }),
      custom_questions: group.custom_questions,
      custom_details: group.custom_details,
    }));
  });

  it("shows configured labels and optional requirements without advertising a disabled passport scanner", () => {
    const source = {
      ...group,
      upload_configuration: {
        ...DEFAULT_UPLOAD_CONFIGURATION,
        passport_enabled: false,
        visa_photo_required: false,
        agent_employee_code_label: "Producer Code",
        agency_dealership_name_label: "Producer Company",
        required_fields: { base_city: false, agent_employee_code: false, agency_dealership_name: false },
      },
    };
    const props = overviewProps(source);
    render(<PassportGroupOverviewPanel {...props} />);
    expect(screen.getByText("Producer Code").parentElement).toHaveTextContent("Optional");
    expect(screen.getByText("Producer Company").parentElement).toHaveTextContent("Optional");
    expect(screen.getByText("Base City").parentElement).toHaveTextContent("Optional");
    expect(screen.getByText("Staff Code").parentElement).toHaveTextContent("Required");
    expect(screen.getByText("Visa Photo").parentElement).toHaveTextContent("Optional");
    expect(screen.getByText("Passport", { exact: true }).parentElement).toHaveTextContent("Disabled");
    expect(screen.getByText("Passport Collection").parentElement).toHaveTextContent("Disabled");
    expect(screen.getByText("Nearest International Airport").parentElement).toHaveTextContent("Disabled");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(props.setTripForm).toHaveBeenCalledWith(expect.objectContaining({
      nearest_international_airport_enabled: false,
      upload_configuration: source.upload_configuration,
      custom_questions: group.custom_questions,
      custom_details: group.custom_details,
    }));
  });
});
