import { Button } from "@/components/ui/button";
import { templateNameError, WHATSAPP_TEMPLATE_NAME_MAX_LENGTH, type WhatsAppTemplateSetting } from "../whatsapp-template-settings";
import type { WhatsAppTemplateSettingsController } from "../hooks/use-whatsapp-template-settings";

export function WhatsAppTemplateNameField({ template, controller }: {
  template: WhatsAppTemplateSetting;
  controller: Pick<WhatsAppTemplateSettingsController, "overrides" | "canEdit" | "busy" | "hasConflict" | "updateOverride">
}) {
  const { overrides, canEdit, busy, hasConflict, updateOverride } = controller;
  const changed = Object.prototype.hasOwnProperty.call(overrides, template.key);
  const selectedOverride = changed ? overrides[template.key] ?? null : template.override_name;
  const value = selectedOverride ?? template.environment_name;
  const error = changed ? templateNameError(selectedOverride) : null;
  const fieldId = `whatsapp-template-${template.key}`;
  return (
    <div
      key={template.key}
      className="grid gap-3 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.35fr)] lg:gap-8"
    >
      <div>
        <label htmlFor={fieldId} className="text-sm font-semibold text-slate-800">
          {template.label}
        </label>
        <p id={`${fieldId}-description`} className="mt-1 text-xs leading-5 text-slate-500">
          {template.contract_description}
        </p>
        <p className="mt-2 text-xs text-slate-500">Language: <span className="font-medium text-slate-700">
          {template.language || "Not configured"}
        </span></p>
      </div>
      <div className="min-w-0 space-y-2">
        <input
          id={fieldId}
          type="text"
          value={value}
          autoComplete="off"
          spellCheck={false}
          autoCapitalize="none"
          maxLength={WHATSAPP_TEMPLATE_NAME_MAX_LENGTH}
          placeholder="Not configured"
          disabled={!canEdit || busy || hasConflict}
          aria-invalid={Boolean(error)}
          aria-describedby={`${fieldId}-description${error ? ` ${fieldId}-error` : ""}`}
          onChange={(event) => updateOverride(template.key, event.target.value)}
          className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 font-mono text-sm text-slate-800 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-500"
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className={`text-xs ${changed ? "text-amber-700" : "text-slate-500"}`}>
            {changed ? "Unsaved · " : ""}
            {selectedOverride === null ? "Environment default" : "Settings override"}
          </span>
          {canEdit && selectedOverride !== null && (
            <Button
              type="button"
              variant="link"
              size="sm"
              disabled={busy || hasConflict}
              onClick={() => updateOverride(template.key, null)}
            >Use environment default</Button>
          )}
        </div>
        {selectedOverride !== null && (
          <p className="break-all text-xs text-slate-500">Environment default: {template.environment_name || "Not configured"}</p>
        )}
        {error && <p id={`${fieldId}-error`} className="text-xs text-red-700">
          {error}
        </p>}
      </div>
    </div>
  );
}
