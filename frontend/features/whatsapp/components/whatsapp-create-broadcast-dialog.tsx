"use client";

import {
  type FormEvent,
  useRef,
  useState,
} from "react";
import { Button, Input } from "@/components/ui";
import { FileSpreadsheet, UsersRound } from "lucide-react";
import type { CreateWhatsAppGroupInput } from "../api/whatsapp-source-groups.api";
import { SourceGroupBroadcastForm } from "./whatsapp-source-group-form";
import {
  ContactEditor,
  DialogFrame,
  ErrorBanner,
  type ManualContact,
  readErrorMessage,
} from "./whatsapp-dialog-ui";
import type {
  WhatsAppRejectedContactInput,
  WhatsAppRecipientInput,
  WhatsAppSupportContactInput,
} from "../api/whatsapp.api";
import {
  ExcelRecipientImport,
  toRejectedContactInputs,
  useRecipientExcelPreview,
} from "./whatsapp-recipient-import";

export function CreateBroadcastDialog({
  isLoading,
  onClose,
  onSubmit,
}: {
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (payload: CreateWhatsAppGroupInput) => Promise<void>;
}) {
  const [method, setMethod] = useState<"contacts" | "source-group">("contacts");
  return (
    <DialogFrame title="Create WhatsApp Broadcast Group" onClose={onClose} isBusy={isLoading}>
      <p className="text-sm text-slate-500">
        Each saved recipient receives a separate WhatsApp message; this does not
        create a shared WhatsApp chat group.
      </p>
      <fieldset className="mt-5" disabled={isLoading}>
        <legend className="mb-2 text-sm font-medium text-slate-700">How would you like to create it?</legend>
        <div className="grid gap-3 sm:grid-cols-2">
          {([
            { value: "contacts", label: "Enter contacts or upload Excel", description: "Add recipients manually or import a spreadsheet.", Icon: FileSpreadsheet },
            { value: "source-group", label: "Create from existing group", description: "Import names and saved WhatsApp numbers from a group.", Icon: UsersRound },
          ] as const).map(({ value, label, description, Icon }) => (
            <label key={value} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition-colors has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-blue-500 ${method === value ? "border-blue-500 bg-blue-50/60" : "border-slate-200 hover:bg-slate-50"}`}>
              <input type="radio" name="broadcast-creation-method" value={value} checked={method === value} onChange={() => setMethod(value)} className="mt-1 h-4 w-4 shrink-0 accent-blue-600" aria-label={label} />
              <span className="min-w-0">
                <span className="flex items-center gap-2 text-sm font-medium text-slate-900"><Icon className="h-4 w-4 shrink-0" aria-hidden="true" />{label}</span>
                <span className="mt-1 block text-xs leading-relaxed text-slate-500">{description}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
      <div hidden={method !== "contacts"}>
        <ManualBroadcastForm isLoading={isLoading} onClose={onClose} onSubmit={onSubmit} />
      </div>
      {method === "source-group" && <SourceGroupBroadcastForm isLoading={isLoading} onClose={onClose} onSubmit={onSubmit} />}
    </DialogFrame>
  );
}

function ManualBroadcastForm({
  isLoading,
  onClose,
  onSubmit,
}: {
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    name: string;
    contacts: WhatsAppRecipientInput[];
    rejectedContacts: WhatsAppRejectedContactInput[];
    supportContacts: WhatsAppSupportContactInput[];
    recipientOptInConfirmed: boolean;
    importedFieldKeys: string[];
  }) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [manual, setManual] = useState<ManualContact>({
    name: "",
    phone_number: "",
  });
  const [contacts, setContacts] = useState<ManualContact[]>([]);
  const [support, setSupport] = useState<ManualContact>({
    name: "",
    phone_number: "",
  });
  const [supportContacts, setSupportContacts] = useState<ManualContact[]>([]);
  const [recipientOptInConfirmed, setRecipientOptInConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitInFlightRef = useRef(false);
  const { importState, previewFile, rejectedContacts, importedFieldKeys } =
    useRecipientExcelPreview({
      contacts,
      setContacts,
      onStart: () => setError(null),
    });

  const addContact = (
    value: ManualContact,
    setter: React.Dispatch<React.SetStateAction<ManualContact[]>>,
    resetter: React.Dispatch<React.SetStateAction<ManualContact>>,
    label: string,
  ) => {
    setError(null);
    if (!value.name.trim() || !value.phone_number.trim()) {
      setError(`Enter both the ${label} name and WhatsApp number.`);
      return;
    }
    setter((current) => [
      ...current,
      { name: value.name.trim(), phone_number: value.phone_number.trim() },
    ]);
    resetter({ name: "", phone_number: "" });
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    if (importState.status === "loading") {
      setError("Wait for the Excel contacts to finish loading.");
      return;
    }
    if (!name.trim()) {
      setError("Enter a group name.");
      return;
    }
    if (contacts.length === 0 && rejectedContacts.length === 0) {
      setError(
        "Add at least one named recipient or import rejected rows for correction.",
      );
      return;
    }
    if (
      contacts.some(
        (contact) => !contact.name.trim() || !contact.phone_number.trim(),
      )
    ) {
      setError("Every recipient needs both a name and WhatsApp number.");
      return;
    }
    if (supportContacts.length === 0) {
      setError("Add at least one customer support contact.");
      return;
    }
    if (contacts.length > 0 && !recipientOptInConfirmed) {
      setError(
        "Confirm that recipients agreed to receive trip updates on WhatsApp.",
      );
      return;
    }
    if (isLoading || submitInFlightRef.current) return;
    submitInFlightRef.current = true;
    try {
      await onSubmit({
        name: name.trim(),
        contacts,
        rejectedContacts: toRejectedContactInputs(rejectedContacts),
        supportContacts,
        recipientOptInConfirmed:
          contacts.length > 0 && recipientOptInConfirmed,
        importedFieldKeys,
      });
    } catch (submitError) {
      setError(
        readErrorMessage(submitError, "Could not save this WhatsApp list."),
      );
    } finally {
      submitInFlightRef.current = false;
    }
  };

  return (
      <form className="mt-5 space-y-5" onSubmit={handleSubmit}>
        <div className="max-w-xl">
          <Input
            label="Group name"
            hint="Used to identify this broadcast and prefill the approved trip wording."
            placeholder="Vietnam Leadership Trip 2026"
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={100}
            required
          />
        </div>

        <ContactEditor
          title="Recipients"
          description="Names are required so staff can identify each recipient and review delivery status."
          value={manual}
          contacts={contacts}
          onValueChange={(value) => {
            setError(null);
            setManual(value);
          }}
          onAdd={() => addContact(manual, setContacts, setManual, "recipient")}
          onRemove={(index) => {
            setError(null);
            setContacts((current) =>
              current.filter((_, itemIndex) => itemIndex !== index),
            );
          }}
          onContactChange={(index, contact) => {
            setError(null);
            setContacts((current) =>
              current.map((item, itemIndex) =>
                itemIndex === index ? contact : item,
              ),
            );
          }}
        />

        <ExcelRecipientImport
          state={importState}
          onFile={previewFile}
          label="Upload Excel contacts"
        />

        <ContactEditor
          title="Passport-link support contacts"
          description="These contacts appear only at the end of the Passport Link message. Welcome messages do not include them."
          value={support}
          contacts={supportContacts}
          onValueChange={setSupport}
          onAdd={() => {
            if (supportContacts.length >= 3) {
              setError("You can add up to three customer support contacts.");
              return;
            }
            addContact(
              support,
              setSupportContacts,
              setSupport,
              "support contact",
            );
          }}
          onRemove={(index) =>
            setSupportContacts((current) =>
              current.filter((_, itemIndex) => itemIndex !== index),
            )
          }
        />

        {contacts.length > 0 ? (
          <label className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 text-sm text-slate-700">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
              checked={recipientOptInConfirmed}
              onChange={(event) =>
                setRecipientOptInConfirmed(event.target.checked)
              }
            />
            <span>
              I confirm these recipients agreed to receive trip-related
              WhatsApp updates and can request that messages stop.
            </span>
          </label>
        ) : rejectedContacts.length > 0 ? (
          <p className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 text-sm text-amber-800">
            This broadcast currently has no valid recipients. Its rejected
            spreadsheet rows will be saved for correction and cannot receive
            WhatsApp messages.
          </p>
        ) : null}

        {error && <ErrorBanner message={error} />}

        <div className="flex justify-end gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={onClose}
            disabled={isLoading}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            isLoading={isLoading}
            disabled={importState.status === "loading"}
          >
            Save List
          </Button>
        </div>
      </form>
  );
}
