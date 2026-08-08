"use client";

import { Pencil, RotateCw } from "lucide-react";
import { Fragment } from "react";
import { formatDateTime } from "@/lib/utils/format";
import type {
  WhatsAppRejectedContact,
  WhatsAppReplacedRecipient,
  WhatsAppRecipientMessageStatus,
  WhatsAppUnidentifiedUpload,
} from "../api/whatsapp.api";

export type RejectedContactCorrection = {
  id: string;
  name: string;
  phoneNumber: string;
  optInConfirmed: boolean;
};

export function importedFieldLabel(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

const ROSTER_SOURCE_FIELD_KEYS = new Set([
  "source_file",
  "source_order",
  "source_sheet",
  "source_row",
]);

export function visibleImportedFieldEntries(
  importedFields: Record<string, string> | null | undefined,
): Array<[string, string]> {
  return Object.entries(importedFields ?? {})
    .filter(([key]) => !ROSTER_SOURCE_FIELD_KEYS.has(key))
    .sort(([left], [right]) =>
      importedFieldLabel(left).localeCompare(importedFieldLabel(right)),
    );
}

function visibleUnidentifiedDetailEntries(
  details: Record<string, unknown>,
): Array<[string, string]> {
  return Object.entries(details)
    .filter(
      ([key, value]) =>
        !ROSTER_SOURCE_FIELD_KEYS.has(key)
        && value !== null
        && value !== undefined
        && value !== "",
    )
    .map(([key, value]): [string, string] => {
      if (typeof value === "string") return [key, value];
      if (typeof value === "number" || typeof value === "boolean") {
        return [key, String(value)];
      }
      try {
        return [key, JSON.stringify(value) ?? String(value)];
      } catch {
        return [key, String(value)];
      }
    })
    .sort(([left], [right]) =>
      importedFieldLabel(left).localeCompare(importedFieldLabel(right)),
    );
}

export function RejectedRosterRows({
  contact,
  serialNumber,
  messageColumnCount,
  correction,
  isSaving,
  onEdit,
  onCorrectionChange,
  onCancel,
  onSave,
}: {
  contact: WhatsAppRejectedContact;
  serialNumber: number;
  messageColumnCount: number;
  correction: RejectedContactCorrection | null;
  isSaving: boolean;
  onEdit: () => void;
  onCorrectionChange: (value: RejectedContactCorrection) => void;
  onCancel: () => void;
  onSave: () => void;
}) {
  const isEditing = correction?.id === contact.id;
  const importedEntries = visibleImportedFieldEntries(
    contact.imported_fields,
  );

  return (
    <Fragment>
      <tr className="bg-amber-50/40">
        <td className="px-4 py-3 text-center font-semibold text-slate-500">
          {serialNumber}
        </td>
        <td className="px-4 py-3">
          <div className="font-medium text-slate-900">
            {contact.raw_name?.trim() || "Unnamed rejected contact"}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {contact.source_file_name} · {contact.sheet_name}, row{" "}
            {contact.row_number}
          </p>
          {importedEntries.length > 0 && (
            <details className="mt-1">
              <summary className="cursor-pointer text-xs font-semibold text-blue-700">
                View {importedEntries.length} imported detail
                {importedEntries.length === 1 ? "" : "s"}
              </summary>
              <dl className="mt-2 grid min-w-64 gap-2 rounded-lg bg-white p-3 sm:grid-cols-2">
                {importedEntries.map(([key, value]) => (
                  <div key={key} className="min-w-0">
                    <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                      {importedFieldLabel(key)}
                    </dt>
                    <dd className="break-words text-xs font-normal text-slate-700">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            </details>
          )}
        </td>
        <td className="px-4 py-3">
          <span className="break-all font-mono text-slate-700">
            {contact.raw_phone_number?.trim() || "Missing"}
          </span>
        </td>
        {Array.from({ length: messageColumnCount }, (_, index) => (
          <td key={index} className="px-4 py-3">
            <span className="inline-flex rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800">
              Rejected
            </span>
          </td>
        ))}
        <td className="px-4 py-3 text-right">
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50"
            aria-expanded={isEditing}
            onClick={onEdit}
          >
            <Pencil className="h-3.5 w-3.5" />
            Correct
          </button>
        </td>
      </tr>
      {isEditing && correction && (
        <tr className="bg-amber-50/40">
          <td colSpan={messageColumnCount + 4} className="px-4 pb-4 pt-0">
            <div className="rounded-xl border border-amber-200 bg-white p-4">
              <p className="mb-3 break-words rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                {contact.reason}
              </p>
              <div className="grid gap-4 md:grid-cols-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-amber-800">
                  Corrected name
                  <input
                    type="text"
                    value={correction.name}
                    className="mt-1.5 w-full rounded-md border border-amber-300 px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                    onChange={(event) =>
                      onCorrectionChange({
                        ...correction,
                        name: event.target.value,
                      })
                    }
                  />
                </label>
                <label className="text-xs font-semibold uppercase tracking-wide text-amber-800">
                  Corrected WhatsApp number
                  <input
                    type="tel"
                    value={correction.phoneNumber}
                    autoFocus
                    className="mt-1.5 w-full rounded-md border border-amber-300 px-2 py-1.5 text-sm font-normal normal-case tracking-normal text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                    onChange={(event) =>
                      onCorrectionChange({
                        ...correction,
                        phoneNumber: event.target.value,
                      })
                    }
                  />
                </label>
              </div>
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-amber-100 pt-3">
                <label className="flex items-start gap-2 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    className="mt-0.5 h-3.5 w-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    checked={correction.optInConfirmed}
                    onChange={(event) =>
                      onCorrectionChange({
                        ...correction,
                        optInConfirmed: event.target.checked,
                      })
                    }
                  />
                  Recipient agreed to WhatsApp updates
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    className="rounded-md px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100"
                    disabled={isSaving}
                    onClick={onCancel}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="rounded-md bg-blue-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={
                      isSaving
                      || !correction.name.trim()
                      || !correction.phoneNumber.trim()
                      || !correction.optInConfirmed
                    }
                    onClick={onSave}
                  >
                    Save and add
                  </button>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

export function ReplacedRosterRow({
  recipient,
  serialNumber,
  messageColumnCount,
  isRestoring,
  onRestore,
}: {
  recipient: WhatsAppReplacedRecipient;
  serialNumber: number;
  messageColumnCount: number;
  isRestoring: boolean;
  onRestore: () => void;
}) {
  const importedEntries = visibleImportedFieldEntries(
    recipient.imported_fields,
  );
  return (
    <tr className="bg-blue-50/40">
      <td className="px-4 py-3 text-center font-semibold text-slate-500">
        {serialNumber}
      </td>
      <td className="px-4 py-3">
        <div className="font-medium text-slate-900">
          {recipient.name?.trim() || "Unnamed recipient"}
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Replaced in {recipient.client_group_name} ·{" "}
          {formatDateTime(recipient.replaced_at)}
        </p>
        <div className="mt-2 rounded-lg border border-blue-200 bg-white px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-blue-700">
            Going instead
          </div>
          <div className="mt-1 text-xs font-semibold text-slate-800">
            {recipient.replacement_name}
          </div>
          <div className="mt-0.5 text-xs text-slate-600">
            {recipient.replacement_phone || "No submitted phone number"}
          </div>
        </div>
        {importedEntries.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs font-semibold text-blue-700">
              View {importedEntries.length} imported detail
              {importedEntries.length === 1 ? "" : "s"}
            </summary>
            <dl className="mt-2 grid min-w-64 gap-2 rounded-lg bg-white p-3 sm:grid-cols-2">
              {importedEntries.map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    {importedFieldLabel(key)}
                  </dt>
                  <dd className="break-words text-xs font-normal text-slate-700">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </details>
        )}
      </td>
      <td className="px-4 py-3">
        <span className="break-all font-mono text-slate-700">
          {recipient.normalized_phone_number}
        </span>
      </td>
      {Array.from({ length: messageColumnCount }, (_, index) => (
        <td key={index} className="px-4 py-3">
          <span className="inline-flex rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800">
            Replaced
          </span>
        </td>
      ))}
      <td className="px-4 py-3 text-right">
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-100 disabled:opacity-50"
          disabled={isRestoring}
          onClick={onRestore}
        >
          <RotateCw className="h-3.5 w-3.5" />
          Restore / add back
        </button>
      </td>
    </tr>
  );
}

export function UnidentifiedRosterRow({
  upload,
  serialNumber,
  messageColumnCount,
}: {
  upload: WhatsAppUnidentifiedUpload;
  serialNumber: number;
  messageColumnCount: number;
}) {
  const detailEntries = visibleUnidentifiedDetailEntries(upload.details);
  return (
    <tr className="bg-red-50/40">
      <td className="px-4 py-3 text-center font-semibold text-slate-500">
        {serialNumber}
      </td>
      <td className="px-4 py-3">
        <div className="font-medium text-slate-900">{upload.name}</div>
        <p className="mt-1 text-xs text-red-700">
          Uploaded in {upload.client_group_name}, but is not in this WhatsApp
          broadcast.
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {upload.email || "No submitted email"} · Updated{" "}
          {formatDateTime(upload.updated_at)}
        </p>
        {detailEntries.length > 0 && (
          <details className="mt-2">
            <summary className="cursor-pointer text-xs font-semibold text-blue-700">
              View {detailEntries.length} submitted detail
              {detailEntries.length === 1 ? "" : "s"}
            </summary>
            <dl className="mt-2 grid min-w-64 gap-2 rounded-lg bg-white p-3 sm:grid-cols-2">
              {detailEntries.map(([key, value]) => (
                <div key={key} className="min-w-0">
                  <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
                    {importedFieldLabel(key)}
                  </dt>
                  <dd className="break-words text-xs font-normal text-slate-700">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </details>
        )}
      </td>
      <td className="px-4 py-3">
        <span className="break-all font-mono text-slate-700">
          {upload.phone_number || "Not provided"}
        </span>
      </td>
      {Array.from({ length: messageColumnCount }, (_, index) => (
        <td key={index} className="px-4 py-3">
          <span className="inline-flex rounded-full border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-semibold text-red-700">
            Not in broadcast
          </span>
        </td>
      ))}
      <td className="px-4 py-3 text-right">
        <a
          href={`/passports/groups/${upload.client_group_id}/whatsapp`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50"
        >
          Review / mark replacement
        </a>
      </td>
    </tr>
  );
}

export function DeliveryBadge({
  status,
}: {
  status: WhatsAppRecipientMessageStatus | null;
}) {
  const isInProgress =
    status?.status === "queued" || status?.status === "processing";
  const isDeliveryUnknown = status?.status === "delivery_unknown";
  const label = status?.already_sent
    ? "Sent"
    : isDeliveryUnknown
      ? "Delivery unknown - review"
      : isInProgress
        ? "In progress"
        : status?.status === "failed"
          ? "Failed"
          : "Not sent";
  const style = status?.already_sent
    ? "bg-emerald-50 text-emerald-700"
    : isDeliveryUnknown
      ? "bg-amber-100 text-amber-800"
      : isInProgress
        ? "bg-blue-50 text-blue-700"
        : status?.status === "failed"
          ? "bg-amber-50 text-amber-700"
          : "bg-slate-100 text-slate-500";
  return (
    <span
      className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${style}`}
    >
      {label}
    </span>
  );
}
