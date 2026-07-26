import type { PassportExcelFieldOptions } from "../api/passports.api";

interface PassportExcelFieldChooserProps {
  options: PassportExcelFieldOptions;
  selectedFields: string[];
  onSelectedFieldsChange: (fields: string[]) => void;
  groupByField: string;
  onGroupByFieldChange: (field: string) => void;
  heading?: string;
}

export function PassportExcelFieldChooser({
  options,
  selectedFields,
  onSelectedFieldsChange,
  groupByField,
  onGroupByFieldChange,
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
      <div>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-950">{heading}</h3>
            <p className="mt-1 text-sm text-slate-600">
              Selected WhatsApp spreadsheet fields appear directly after the four trip columns.
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
          {options.fields.map((field) => (
            <label
              key={field.key}
              className="flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-3 hover:border-blue-300 hover:bg-blue-50/40"
            >
              <input
                type="checkbox"
                checked={selectedFields.includes(field.key)}
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
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-slate-900">
                  {field.label}
                </span>
                <span className="text-xs text-slate-500">
                  WhatsApp spreadsheet
                </span>
              </span>
            </label>
          ))}
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
