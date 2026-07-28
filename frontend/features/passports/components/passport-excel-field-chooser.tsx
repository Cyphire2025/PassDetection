import type {
  PassportExcelFieldOptions,
  PassportGroupExportFieldOption,
} from "../api/passports.api";

interface AgencyMatchSelection {
  fields: PassportGroupExportFieldOption[];
  selectedField: string;
  onSelectedFieldChange: (field: string) => void;
}

interface PassportExcelFieldChooserProps {
  options: PassportExcelFieldOptions;
  selectedFields: string[];
  onSelectedFieldsChange: (fields: string[]) => void;
  groupByField: string;
  onGroupByFieldChange: (field: string) => void;
  agencyMatch?: AgencyMatchSelection;
  heading?: string;
}

export function PassportExcelFieldChooser({
  options,
  selectedFields,
  onSelectedFieldsChange,
  groupByField,
  onGroupByFieldChange,
  agencyMatch,
  heading = "Choose Excel columns",
}: PassportExcelFieldChooserProps) {
  const allSelected = (
    options.fields.length > 0
    && selectedFields.length === options.fields.length
  );
  const fixedGroupingKeys = new Set(
    options.grouping_fields
      .filter((field) => field.fixed)
      .map((field) => field.key),
  );

  return (
    <div className="space-y-5">
      {agencyMatch && (
        <label className="block space-y-2 rounded-xl border border-blue-200 bg-blue-50/60 p-4">
          <span className="block font-semibold text-slate-950">
            Match by Agency/Dealership Name
          </span>
          <span className="block text-sm text-slate-600">
            Select the WhatsApp spreadsheet column that contains the agency or
            dealership name entered by the traveller. Matching ignores case,
            spacing, and punctuation, and accepts a unique match of 90% or higher.
          </span>
          <select
            value={agencyMatch.selectedField}
            onChange={(event) => (
              agencyMatch.onSelectedFieldChange(event.target.value)
            )}
            className="h-11 w-full rounded-lg border border-blue-200 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">Do not use agency matching</option>
            {agencyMatch.fields.map((field) => (
              <option key={field.key} value={field.key}>
                {field.label}
              </option>
            ))}
          </select>
          {agencyMatch.selectedField && (
            <span className="block text-xs font-medium text-blue-800">
              Matched WhatsApp names will be exported as Old Surname and Old
              Given Name. Passport names will be exported as New Surname and
              New Given Name.
            </span>
          )}
          {agencyMatch.fields.length === 0 && (
            <span className="block text-xs font-medium text-amber-700">
              No linked WhatsApp spreadsheet fields are available for matching.
            </span>
          )}
        </label>
      )}

      <div>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-950">{heading}</h3>
            <p className="mt-1 text-sm text-slate-600">
              Select fields in the order they should appear after the four trip
              columns. Each selected field shows its Excel column order.
            </p>
          </div>
          {options.fields.length > 0 && (
            <button
              type="button"
              className="shrink-0 text-sm font-semibold text-blue-700 hover:underline"
              onClick={() => {
                if (allSelected) {
                  onSelectedFieldsChange([]);
                  if (!fixedGroupingKeys.has(groupByField)) {
                    onGroupByFieldChange("");
                  }
                  return;
                }
                onSelectedFieldsChange(options.fields.map((field) => field.key));
              }}
            >
              {allSelected ? "Clear all" : "Select all"}
            </button>
          )}
        </div>

        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {options.fields.map((field) => {
            const selectedOrder = selectedFields.indexOf(field.key) + 1;
            return (
              <label
                key={field.key}
                className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-3 hover:border-blue-300 hover:bg-blue-50/40"
              >
                <input
                  type="checkbox"
                  checked={selectedOrder > 0}
                  onChange={(event) => {
                    if (event.target.checked) {
                      onSelectedFieldsChange([...selectedFields, field.key]);
                      return;
                    }
                    onSelectedFieldsChange(
                      selectedFields.filter((key) => key !== field.key),
                    );
                    if (groupByField === field.key) {
                      onGroupByFieldChange("");
                    }
                  }}
                  className="mt-1 h-4 w-4 accent-blue-600"
                />
                <span
                  aria-hidden="true"
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                    selectedOrder > 0
                      ? "bg-blue-600 text-white"
                      : "bg-slate-100 text-slate-400"
                  }`}
                >
                  {selectedOrder > 0 ? selectedOrder : "—"}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-slate-900">
                    {field.label}
                  </span>
                  <span className="text-xs text-slate-500">
                    WhatsApp spreadsheet
                  </span>
                </span>
              </label>
            );
          })}
        </div>

        {options.fields.length === 0 && (
          <div className="mt-3 rounded-xl border border-dashed border-slate-300 p-4 text-sm text-slate-500">
            No additional saved fields are available. The standard passport template will still be exported.
          </div>
        )}
      </div>

      <label className="block space-y-2 rounded-xl border border-slate-200 bg-slate-50 p-4">
        <span className="block font-semibold text-slate-900">Sort by</span>
        <span className="block text-sm text-slate-600">
          Groups equal values together and adds blank rows between groups.
        </span>
        <select
          value={groupByField}
          onChange={(event) => onGroupByFieldChange(event.target.value)}
          className="h-11 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          <option value="">No grouping</option>
          {options.grouping_fields
            .filter((field) => (
              field.fixed || selectedFields.includes(field.key)
            ))
            .map((field) => (
              <option key={field.key} value={field.key}>
                {field.label}
              </option>
            ))}
        </select>
      </label>
    </div>
  );
}
