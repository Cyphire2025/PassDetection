"use client";

import { useId, useState } from "react";
import type { PassportGroupExportKind, PassportImageType } from "../api/passports.api";
import type { PassportImageRevisions } from "../utils/passport-image-revisions";
import { DEFAULT_TRIP_TIMEZONE } from "../utils/trip-timezone";
import type { TripDetailsForm } from "./passport-trip-details-dialog";

export function usePassportGroupDialogState() {
  const [imageRevisions, setImageRevisions] = useState<PassportImageRevisions>({});
  const [imageEditor, setImageEditor] = useState<{
    submissionId: string;
    imageType: PassportImageType;
    label: string;
    returnFocusTarget: HTMLButtonElement;
  } | null>(null);
  const [isTripDetailsExpanded, setIsTripDetailsExpanded] = useState(false);
  const tripDetailsRegionId = useId();
  const [isExpiryAlertsExpanded, setIsExpiryAlertsExpanded] = useState(false);
  const expiryAlertsRegionId = useId();
  const [exportDialogKind, setExportDialogKind] = useState<PassportGroupExportKind | null>(null);
  const [isBulkDeleteConfirmationOpen, setIsBulkDeleteConfirmationOpen] = useState(false);
  const [isBulkApprovalConfirmationOpen, setIsBulkApprovalConfirmationOpen] = useState(false);
  const [displayNameEditorId, setDisplayNameEditorId] = useState<string | null>(null);
  const [isEditingTrip, setIsEditingTrip] = useState(false);
  const [tripForm, setTripForm] = useState<TripDetailsForm>({
    name: "",
    destination: "",
    travel_date: "",
    return_date: "",
    timezone: DEFAULT_TRIP_TIMEZONE,
    departure_cities: [] as string[],
    base_city_enabled: false,
    nearest_international_airport_enabled: false,
    staff_code_enabled: false,
    agent_employee_code_enabled: false,
    meal_preference_enabled: false,
    require_selfie: false,
    allow_files_from_device: true,
    ask_nearest_domestic_airport: false,
    relation_with_qualifier_enabled: false,
    designation_enabled: false,
    agency_dealership_name_enabled: false,
    notes: "",
  });
  return {
    imageRevisions,
    setImageRevisions,
    imageEditor,
    setImageEditor,
    isTripDetailsExpanded,
    setIsTripDetailsExpanded,
    tripDetailsRegionId,
    isExpiryAlertsExpanded,
    setIsExpiryAlertsExpanded,
    expiryAlertsRegionId,
    exportDialogKind,
    setExportDialogKind,
    isBulkDeleteConfirmationOpen,
    setIsBulkDeleteConfirmationOpen,
    isBulkApprovalConfirmationOpen,
    setIsBulkApprovalConfirmationOpen,
    displayNameEditorId,
    setDisplayNameEditorId,
    isEditingTrip,
    setIsEditingTrip,
    tripForm,
    setTripForm,
  };
}
