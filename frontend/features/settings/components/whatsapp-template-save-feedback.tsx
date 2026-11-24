import { Button } from "@/components/ui/button";
import { Check, Save } from "lucide-react";
import type { WhatsAppTemplateSettingsController } from "../hooks/use-whatsapp-template-settings";

export function WhatsAppTemplateSaveFeedback({ controller }: { controller: Pick<WhatsAppTemplateSettingsController, "canEdit" | "saveError" | "saveMessage" | "hasChanges" | "isSaving" | "invalid" | "hasConflict" | "busy" | "save"> }) {
  const { canEdit, saveError, saveMessage, hasChanges, isSaving, invalid, hasConflict, busy, save } = controller;
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 border-t border-slate-100 bg-slate-50/50 px-6 py-4">
      <div className="min-w-0 flex-1 text-sm" aria-live="polite">
        {saveError ? <p className="text-red-700" role="alert">
          {saveError}
        </p> : saveMessage ? (
          <p className="flex items-center gap-2 text-emerald-700">
            <Check className="h-4 w-4 shrink-0" />
            {saveMessage}
          </p>
        ) : (
          <p className="text-slate-500">
            {hasChanges ? "You have unsaved template changes. Reloading will discard them." : "Changes apply to new sends after saving."}
          </p>
        )}
      </div>
      {canEdit && (
        <Button
          type="button"
          onClick={save}
          isLoading={isSaving}
          disabled={!hasChanges || invalid || hasConflict || busy}
          leftIcon={<Save className="h-4 w-4" />}
        >Save template settings</Button>
      )}
    </div>
  );
}
