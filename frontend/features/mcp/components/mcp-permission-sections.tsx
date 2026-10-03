"use client";

import { Badge } from "@/components/ui";
import type { McpPermissionSection } from "../api/mcp.api";
import { McpPermissionSwitch } from "./mcp-permission-switch";

export function McpPermissionSections({ mode, sections, selected, disabled, onChange }: {
  mode: "read" | "write"; sections: McpPermissionSection[]; selected: string[];
  disabled: boolean; onChange: (sections: string[]) => void;
}) {
  return <fieldset disabled={disabled} className="divide-y divide-slate-100 rounded-xl border border-slate-200">
    <legend className="sr-only">{mode === "read" ? "Read sections" : "Write sections"}</legend>
    {sections.map((section) => {
      const supported = mode === "read" ? section.read_supported : section.write_supported;
      const description = mode === "read" ? section.read_description : section.write_description;
      return <div key={section.id} className="px-4 py-4 sm:px-5">
        {supported ? <McpPermissionSwitch label={`${mode === "read" ? "Read" : "Write"} ${section.label}`} description={description}
          checked={selected.includes(section.id)} onChange={(checked) => onChange(checked ? [...selected, section.id] : selected.filter((id) => id !== section.id))} />
          : <div><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium text-slate-800">{section.label}</p><Badge variant="outline">Not available</Badge></div>
            <p className="mt-1 text-xs leading-5 text-slate-500">{description || `No ${mode} actions are available for this section.`}</p></div>}
      </div>;
    })}
  </fieldset>;
}
