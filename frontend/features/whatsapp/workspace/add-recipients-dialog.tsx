"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui";
import { useAddWhatsAppRecipients } from "../hooks/use-whatsapp";
import {
  ContactEditor,
  DialogFrame,
  ErrorBanner,
  readErrorMessage,
  type ManualContact,
} from "../components/whatsapp-dialog-ui";
import {
  ExcelRecipientImport,
  toRejectedContactInputs,
  useRecipientExcelPreview,
} from "../components/whatsapp-recipient-import";
import { useBroadcast } from "./broadcast-workspace-shell";

export function AddRecipientsDialog({ onClose }: { onClose: () => void }) {
  const group = useBroadcast();
  const mutation = useAddWhatsAppRecipients();
  const [contacts, setContacts] = useState<ManualContact[]>([]);
  const [manual, setManual] = useState<ManualContact>({
    name: "",
    phone_number: "",
  });
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const imported = useRecipientExcelPreview({
    contacts,
    setContacts,
    excludedPhoneNumbers: group.recipients.map(
      (recipient) => recipient.normalized_phone_number,
    ),
    onStart: () => setError(null),
  });
  const busy = mutation.isPending || imported.importState.status === "loading";
  const ready =
    !busy &&
    imported.importState.status !== "error" &&
    (contacts.length > 0 || imported.rejectedContactCount > 0) &&
    (contacts.length === 0 || confirmed);
  return (
    <DialogFrame
      title="Add recipients"
      description="Enter contacts manually or import an Excel workbook."
      onClose={onClose}
      isBusy={busy}
      widthClass="max-w-3xl"
    >
      <div className="space-y-5">
        <ExcelRecipientImport
          state={imported.importState}
          label="Import recipients from Excel"
          onFile={imported.previewFile}
          onDismissError={imported.dismissImportError}
        />
        <ContactEditor
          title="Recipients to add"
          description="Review the names and WhatsApp numbers before saving."
          value={manual}
          contacts={contacts}
          onValueChange={setManual}
          onAdd={() => {
            setContacts((current) => [
              ...current,
              {
                name: manual.name.trim(),
                phone_number: manual.phone_number.trim(),
              },
            ]);
            setManual({ name: "", phone_number: "" });
          }}
          onRemove={(index) =>
            setContacts((current) =>
              current.filter((_, position) => position !== index),
            )
          }
          onContactChange={(index, contact) =>
            setContacts((current) =>
              current.map((entry, position) =>
                position === index ? contact : entry,
              ),
            )
          }
        />
        {contacts.length > 0 && (
          <label className="flex items-start gap-2 text-sm text-slate-600">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              className="mt-1 accent-blue-600"
            />
            I confirm these recipients agreed to receive trip-related WhatsApp
            updates.
          </label>
        )}
        {error && <ErrorBanner message={error} />}
        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            disabled={!ready}
            isLoading={mutation.isPending}
            onClick={async () => {
              if (lock.current || !ready) return;
              lock.current = true;
              setError(null);
              try {
                await mutation.mutateAsync({
                  groupId: group.id,
                  contacts,
                  rejectedContacts: toRejectedContactInputs(
                    imported.rejectedContacts,
                  ),
                  recipientOptInConfirmed: confirmed,
                  importedFieldKeys: imported.importedFieldKeys,
                  duplicateSourceFiles: imported.duplicateSourceFiles,
                });
                onClose();
              } catch (cause) {
                setError(readErrorMessage(cause, "Could not add recipients."));
              } finally {
                lock.current = false;
              }
            }}
          >
            Add recipients{contacts.length > 0 ? ` (${contacts.length})` : ""}
          </Button>
        </div>
      </div>
    </DialogFrame>
  );
}
