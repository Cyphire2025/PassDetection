"use client";

import { Badge } from "@/components/ui";
import type { McpPermissionSection } from "../api/mcp.api";
import { mcpSectionDescription } from "../utils/section-copy";
import { McpPermissionSwitch } from "./mcp-permission-switch";

export function McpPermissionSections({ mode, sections, selected, disabled, onChange }: {
  mode: "read" | "write"; sections: McpPermissionSection[]; selected: string[];
  disabled: boolean; onChange: (sections: string[]) => void;
}) {
  return <fieldset disabled={disabled} className="divide-y divide-slate-100 rounded-xl border border-slate-200">
    <legend className="sr-only">{mode === "read" ? "Read sections" : "Write sections"}</legend>
    {sections.filter((section) => mode === "read" ? section.read_supported : section.write_supported).map((section) => {
      const description = mcpSectionDescription(mode, section.id, mode === "read" ? section.read_description : section.write_description);
      const enabledBySettings = mode !== "write" || section.write_allowed_by_settings !== false;
      return <div key={section.id} className="px-4 py-4 sm:px-5">
        <McpPermissionSwitch label={`${mode === "read" ? "Read" : "Write"} ${section.label}`} description={description}
          checked={selected.includes(section.id)} disabled={!enabledBySettings}
          onChange={(checked) => onChange(checked ? [...selected, section.id] : selected.filter((id) => id !== section.id))} />
        {!enabledBySettings ? <div className="mt-2 flex flex-wrap items-center gap-2 text-xs leading-5 text-slate-500">
          <Badge variant="outline">Off in Settings</Badge>
          <span>Enable this action in Settings → Write access before allowing it for this device.</span>
        </div> : null}
      </div>;
    })}
  </fieldset>;
}
