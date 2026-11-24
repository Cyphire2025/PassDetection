"use client";

import { usePassportGroups } from "../hooks/use-passports";
import { useUploadLinks } from "../hooks/use-upload-links";

export function usePassportGroupMetadata(groupId: string, includeDeleted: boolean) {
  const { data: groups = [] } = usePassportGroups();
  const { data: deletedGroups = [] } = useUploadLinks("deleted", includeDeleted);
  const deletedGroup = deletedGroups.find((item) => item.id === groupId);
  const group = groups.find((item) => item.group_id === groupId);
  const groupDetails = group ??
    (deletedGroup
      ? {
        group_id: deletedGroup.id,
        group_name: deletedGroup.name,
        banner_url: deletedGroup.banner_url,
        background_url: deletedGroup.background_url,
        group_status: deletedGroup.status,
        import_only: deletedGroup.import_only,
        total_passports: deletedGroup.deleted_passport_count,
        pending_review_count: 0,
        confirmed_count: 0,
        failed_count: 0,
        latest_submission_at: deletedGroup.deleted_at ?? deletedGroup.created_at,
        destination: deletedGroup.destination,
        travel_date: deletedGroup.travel_date,
        return_date: deletedGroup.return_date,
        timezone: deletedGroup.timezone,
        package_name: deletedGroup.package_name,
        departure_cities: deletedGroup.departure_cities ?? [],
        base_city_enabled: deletedGroup.base_city_enabled,
        nearest_international_airport_enabled: deletedGroup.nearest_international_airport_enabled,
        staff_code_enabled: deletedGroup.staff_code_enabled,
        agent_employee_code_enabled: deletedGroup.agent_employee_code_enabled,
        meal_preference_enabled: deletedGroup.meal_preference_enabled,
        require_selfie: deletedGroup.require_selfie,
        upload_configuration: deletedGroup.upload_configuration,
        custom_questions: deletedGroup.custom_questions,
        custom_details: deletedGroup.custom_details,
        allow_files_from_device: deletedGroup.allow_files_from_device ?? true,
        ask_nearest_domestic_airport: deletedGroup.ask_nearest_domestic_airport ?? false,
        relation_with_qualifier_enabled: deletedGroup.relation_with_qualifier_enabled ?? false,
        designation_enabled: deletedGroup.designation_enabled ?? false,
        agency_dealership_name_enabled: deletedGroup.agency_dealership_name_enabled ?? false,
        notes: deletedGroup.notes,
      }
      : undefined);
  return { groupDetails };
}
