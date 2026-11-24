import { Loader2 } from "lucide-react";
import { PassportExcelFieldChooser } from "./passport-excel-field-chooser";
import type { PassportExportDialogState } from "./use-passport-export-dialog";

export function PassportExportFields({ state }: { state: PassportExportDialogState }) {
  const {
    exportFields,
    selectedFields,
    setSelectedFields,
    groupByField,
    setGroupByField,
    agencyMatchField,
    setAgencyMatchField
  } = state;
  return (exportFields.isLoading ? (
    <div className="flex min-h-44 items-center justify-center gap-2 text-sm text-slate-600">
      <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
      Loading saved Excel fields
    </div>
  ) : exportFields.error ? (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
      Saved Excel fields could not be loaded. Go back and try again.
    </div>
  ) : exportFields.data ? (
    <PassportExcelFieldChooser
      options={exportFields.data}
      selectedFields={selectedFields}
      onSelectedFieldsChange={setSelectedFields}
      groupByField={groupByField}
      onGroupByFieldChange={setGroupByField}
      agencyMatch={exportFields.data.agency_match_enabled ? {
        fields: exportFields.data.agency_match_fields,
        selectedField: agencyMatchField,
        onSelectedFieldChange: setAgencyMatchField,
      } : undefined}
      heading="Step 2: Choose Excel columns"
    />
  ) : null);
}
