"use client";

import type { CompanyReference } from "../types";
import { CompanyPicker } from "./company-picker";

/** The enclosing group form owns the draft and its single save action. */
export function GroupCompanyAssignment({ agencyId, selected, onChange, disabled }: {
  agencyId: string;
  selected: CompanyReference | null;
  onChange: (company: CompanyReference) => void;
  disabled?: boolean;
}) {
  return <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50/60 p-4">
    <CompanyPicker agencyId={agencyId} value={selected} onChange={onChange} disabled={disabled} />
    <p className="text-xs leading-5 text-slate-500">Save changes applies the selected company. Closed and archived groups keep their status and existing records. Changing an existing company may require a reassignment review.</p>
  </div>;
}
