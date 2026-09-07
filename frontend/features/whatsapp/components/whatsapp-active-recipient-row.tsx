"use client";

import { MoreHorizontal, Pencil, RotateCw, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { WhatsAppRecipient } from "../api/whatsapp.api";
import { formatMessageType, isWhatsAppMessageType } from "../utils/message-types";
import { getMessageStatus, hasAlreadySentMessage } from "../utils/recipient-delivery";
import type { RecipientResendTarget } from "./whatsapp-workspace.types";
import { DeliveryBadge, importedFieldLabel, visibleImportedFieldEntries } from "./whatsapp-recipient-roster-rows";
import { RecipientSelectionCheckbox } from "./whatsapp-recipient-selection";

export function ActiveRecipientRow({
  recipient, serialNumber, messageTypes, selected, selectionDisabled, onSelect,
  editing, editedPhone, onPhoneChange, onEdit, onCancelEdit, onSavePhone,
  phoneSaving, resendPending, onResend, removeDisabled, onRemove,
}: {
  recipient: WhatsAppRecipient;
  serialNumber: number;
  messageTypes: string[];
  selected: boolean;
  selectionDisabled: boolean;
  onSelect: (checked: boolean) => void;
  editing: boolean;
  editedPhone: string;
  onPhoneChange: (phone: string) => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSavePhone: () => void;
  phoneSaving: boolean;
  resendPending: boolean;
  onResend: (target: RecipientResendTarget) => void;
  removeDisabled: boolean;
  onRemove: () => void;
}) {
  const menuRef = useRef<HTMLDetailsElement>(null);
  const [menuPosition, setMenuPosition] = useState<{ top: number; right: number } | null>(null);
  const name = recipient.name || "Unnamed recipient";
  const importedEntries = visibleImportedFieldEntries(recipient.imported_fields);
  const resendActions = messageTypes.flatMap((messageType) => {
    if (!isWhatsAppMessageType(messageType)) return [];
    const status = getMessageStatus(recipient, messageType);
    const canRetry = status?.status === "failed";
    if (!canRetry && !hasAlreadySentMessage(recipient, messageType)) return [];
    return [{ messageType, status, action: canRetry ? "retry" as const : "resend" as const }];
  });
  const closeMenu = () => { if (menuRef.current) menuRef.current.open = false; };
  useEffect(() => {
    if (!menuPosition) return;
    const handleMenuKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !(event.target instanceof Node) || !menuRef.current?.contains(event.target)) return;
      // Stop Escape before the dialog's native document listener sees it.
      event.preventDefault();
      event.stopPropagation();
      closeMenu();
      menuRef.current.querySelector("summary")?.focus();
    };
    const dismiss = (event: Event) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return;
      closeMenu();
    };
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", handleMenuKeyDown, true);
    document.addEventListener("wheel", dismiss, { passive: true, capture: true });
    document.addEventListener("touchmove", dismiss, { passive: true, capture: true });
    window.addEventListener("resize", closeMenu);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", handleMenuKeyDown, true);
      document.removeEventListener("wheel", dismiss, true);
      document.removeEventListener("touchmove", dismiss, true);
      window.removeEventListener("resize", closeMenu);
    };
  }, [menuPosition]);

  return (
    <tr className={`transition-colors ${selected ? "bg-blue-50/70" : "hover:bg-slate-50/70"}`}>
      <td className="w-12 px-4 py-4 text-center">
        <RecipientSelectionCheckbox checked={selected} disabled={selectionDisabled} label={`Select ${name}`} onChange={onSelect} />
      </td>
      <td className="w-12 px-2 py-4 text-center text-xs tabular-nums text-slate-400">{serialNumber}</td>
      <td className="min-w-44 px-4 py-4">
        <div className="font-semibold text-slate-800">{name}</div>
        {importedEntries.length > 0 && (
          <details className="mt-1">
            <summary className="cursor-pointer text-xs text-slate-500 hover:text-blue-700">{importedEntries.length} imported {importedEntries.length === 1 ? "detail" : "details"}</summary>
            <dl className="mt-2 grid min-w-56 gap-2 rounded-lg border border-slate-200 bg-white p-3">
              {importedEntries.map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{importedFieldLabel(key)}</dt><dd className="break-words text-xs text-slate-700">{value}</dd></div>)}
            </dl>
          </details>
        )}
      </td>
      <td className="px-4 py-4 text-slate-600">
        {editing ? (
          <div className="min-w-56 space-y-2">
            <input type="tel" value={editedPhone} autoFocus aria-label={`WhatsApp number for ${name}`} className="w-full rounded-lg border border-slate-300 px-2.5 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" onChange={(event) => onPhoneChange(event.target.value)} />
            <div className="flex gap-2">
              <button type="button" className="rounded-md px-2 py-1.5 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:opacity-50" disabled={phoneSaving || !editedPhone.trim()} onClick={onSavePhone}>Save</button>
              <button type="button" className="rounded-md px-2 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-100" disabled={phoneSaving} onClick={onCancelEdit}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 whitespace-nowrap text-xs tabular-nums">
            <span>{recipient.normalized_phone_number}</span>
            <button type="button" className="rounded-md p-1.5 text-slate-400 hover:bg-blue-50 hover:text-blue-700" aria-label={`Edit WhatsApp number for ${name}`} onClick={onEdit} disabled={selectionDisabled}><Pencil className="h-3.5 w-3.5" /></button>
          </div>
        )}
      </td>
      {messageTypes.map((messageType) => {
        const status = getMessageStatus(recipient, messageType);
        const latest = status?.latest_resend_status;
        return (
          <td key={messageType} className="px-4 py-4">
            <DeliveryBadge status={status} />
            {latest && <p className={`mt-1.5 text-[11px] ${latest === "failed" ? "text-red-600" : latest === "delivery_unknown" ? "text-amber-700" : "text-slate-500"}`}>
              {latest === "failed" ? "Last resend failed" : latest === "delivery_unknown" ? "Resend needs review" : latest === "queued" || latest === "processing" ? "Resending…" : ["sent", "delivered", "read"].includes(latest) ? "Resent" : null}
            </p>}
          </td>
        );
      })}
      <td className="px-4 py-4 text-right">
        <details ref={menuRef} className="relative inline-block text-left" onToggle={(event) => {
          if (!event.currentTarget.open) { setMenuPosition(null); return; }
          const bounds = event.currentTarget.getBoundingClientRect();
          const menuHeight = event.currentTarget.querySelector<HTMLElement>("[data-recipient-menu-content]")?.getBoundingClientRect().height ?? 300;
          const dialogBounds = event.currentTarget.closest('[role="dialog"]')?.getBoundingClientRect();
          const upperLimit = Math.max(12, (dialogBounds?.top ?? 0) + 12);
          const lowerLimit = Math.min(window.innerHeight - 12, (dialogBounds?.bottom ?? window.innerHeight) - 12);
          const top = bounds.bottom + menuHeight + 6 <= lowerLimit ? bounds.bottom + 6 : bounds.top - menuHeight - 6;
          setMenuPosition({ top: Math.max(upperLimit, Math.min(top, lowerLimit - menuHeight)), right: Math.max(12, window.innerWidth - bounds.right) });
        }} onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); closeMenu(); menuRef.current?.querySelector("summary")?.focus(); } }}>
          <summary aria-label={`Actions for ${name}`} className="flex h-8 w-8 cursor-pointer list-none items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 [&::-webkit-details-marker]:hidden"><MoreHorizontal className="h-4 w-4" /></summary>
          <div data-recipient-menu-content style={menuPosition ?? undefined} className="fixed z-[60] min-w-56 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl">
            <p className="px-2.5 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">For this recipient</p>
            {resendActions.map(({ messageType, status, action }) => (
              <button key={messageType} type="button" className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2.5 text-left text-xs font-medium text-slate-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-40" disabled={resendPending || status?.resend_blocked || selectionDisabled} title={status?.resend_blocked ? "A send is in progress or its delivery needs review." : undefined} aria-label={`${action === "retry" ? "Retry" : "Resend"} ${formatMessageType(messageType)} to ${name}`} onClick={() => { closeMenu(); onResend({ recipientId: recipient.id, recipientName: name, phoneNumber: recipient.normalized_phone_number, messageType, action }); }}>
                <RotateCw className="h-3.5 w-3.5" /> {action === "retry" ? "Retry" : "Resend"} {formatMessageType(messageType).toLowerCase()}
              </button>
            ))}
            <button type="button" className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2.5 text-left text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40" disabled={selectionDisabled} onClick={() => { closeMenu(); onEdit(); }}><Pencil className="h-3.5 w-3.5" /> Edit WhatsApp number</button>
            <div className="my-1 border-t border-slate-100" />
            <button type="button" className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2.5 text-left text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-40" disabled={removeDisabled || selectionDisabled} aria-label={`Remove ${name} from broadcast`} title={removeDisabled ? "A broadcast must keep at least one recipient" : undefined} onClick={() => { closeMenu(); onRemove(); }}><Trash2 className="h-3.5 w-3.5" /> Remove recipient</button>
          </div>
        </details>
      </td>
    </tr>
  );
}
