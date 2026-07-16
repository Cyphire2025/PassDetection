"use client";

import {
  FileSpreadsheet,
  Info,
  MessageCircle,
  MoreVertical,
  Plus,
  Send,
  Upload,
  Users,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import type {
  WhatsAppBroadcastGroup,
  WhatsAppMessageType,
  WhatsAppPreviewResponse,
  WhatsAppRecipientInput,
  WhatsAppSendResponse,
  WhatsAppSupportContactInput,
} from "../api/whatsapp.api";
import {
  useCreateWhatsAppGroup,
  usePreviewWhatsAppMessage,
  useSendWhatsAppPassportLink,
  useSendWhatsAppWelcome,
  WHATSAPP_BATCH_POLL_LIMIT_MS,
  useWhatsAppBatchStatus,
  useWhatsAppGroup,
  useWhatsAppGroups,
} from "../hooks/use-whatsapp";

type ManualContact = {
  name: string;
  phone_number: string;
};

type MessageTarget = {
  group: WhatsAppBroadcastGroup;
  messageType: WhatsAppMessageType;
};

type PersistedBatch = {
  id: string;
  startedAt: number;
};

const LAST_BATCH_STORAGE_KEY = "passdetection:whatsapp:last-batch";

export function WhatsAppPage() {
  const { data: groups = [], isLoading, error } = useWhatsAppGroups();
  const createGroup = useCreateWhatsAppGroup();
  const sendWelcome = useSendWhatsAppWelcome();
  const sendPassportLink = useSendWhatsAppPassportLink();
  const [showCreate, setShowCreate] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [messageTarget, setMessageTarget] = useState<MessageTarget | null>(null);
  const [lastSend, setLastSend] = useState<WhatsAppSendResponse | null>(null);
  const [persistedBatch, setPersistedBatch] = useState<PersistedBatch | null>(() => {
    if (typeof window === "undefined") return null;
    try {
      const saved = window.sessionStorage.getItem(LAST_BATCH_STORAGE_KEY);
      return saved ? JSON.parse(saved) as PersistedBatch : null;
    } catch {
      return null;
    }
  });
  const activeBatchId = lastSend?.batch_id ?? persistedBatch?.id ?? null;
  const { data: currentBatch } = useWhatsAppBatchStatus(
    activeBatchId,
    persistedBatch?.startedAt ?? null,
  );
  const displayedSend = currentBatch ?? lastSend;
  const pollingTimedOut = Boolean(
    currentBatch?.queued
    && persistedBatch
    && Date.now() - persistedBatch.startedAt >= WHATSAPP_BATCH_POLL_LIMIT_MS,
  );

  useEffect(() => {
    if (!currentBatch || currentBatch.queued > 0 || typeof window === "undefined") return;
    window.sessionStorage.removeItem(LAST_BATCH_STORAGE_KEY);
  }, [currentBatch]);

  const openMessagePreview = (
    group: WhatsAppBroadcastGroup,
    messageType: WhatsAppMessageType,
  ) => {
    setOpenMenuId(null);
    setMessageTarget({ group, messageType });
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">WhatsApp</h1>
          <p className="mt-1 text-slate-500">
            Create recipient lists and send approved trip messages to each person individually.
          </p>
        </div>
        <Button type="button" onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4" />
          Create
        </Button>
      </div>

      {displayedSend && (
        <div
          className={`rounded-xl border px-4 py-3 text-sm ${
            displayedSend.failed > 0
              ? "border-amber-200 bg-amber-50 text-amber-800"
              : displayedSend.queued > 0
                ? "border-blue-200 bg-blue-50 text-blue-800"
                : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {displayedSend.queued > 0 && (
            <>
              {displayedSend.queued} message{displayedSend.queued === 1 ? " is" : "s are"} queued for individual delivery. {pollingTimedOut && "Automatic status checks paused; refresh this page later. "}
            </>
          )}
          {displayedSend.sent > 0 && (
            <>{displayedSend.sent} submitted to WhatsApp. </>
          )}
          {displayedSend.failed > 0 && (
            <>{displayedSend.failed} failed; review the provider configuration or recipient numbers.</>
          )}
        </div>
      )}

      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          WhatsApp lists could not be loaded. Check that the backend is reachable.
        </div>
      ) : isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : groups.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center px-6 py-16 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
              <MessageCircle className="h-6 w-6" />
            </span>
            <h2 className="mt-4 font-semibold text-slate-900">No WhatsApp lists yet</h2>
            <p className="mt-1 max-w-md text-sm text-slate-500">
              Add recipients manually or upload an Excel file to prepare the first individual broadcast.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[850px] text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 font-medium text-slate-600">
                  <tr>
                    <th className="px-6 py-4">Group Name</th>
                    <th className="px-6 py-4">Organising Company</th>
                    <th className="px-6 py-4">Recipients</th>
                    <th className="px-6 py-4">Updated</th>
                    <th className="px-6 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {groups.map((group) => (
                    <tr key={group.id} className="transition-colors hover:bg-slate-50/50">
                      <td className="px-6 py-4">
                        <div className="font-medium text-slate-900">{group.name}</div>
                        <div className="mt-1 text-xs text-slate-500">Shown inside client messages</div>
                      </td>
                      <td className="px-6 py-4 text-slate-700">
                        {group.organizing_company_name || "Not set"}
                      </td>
                      <td className="px-6 py-4 text-slate-700">
                        <span className="inline-flex items-center gap-1.5">
                          <Users className="h-4 w-4 text-slate-400" />
                          {group.recipient_count}
                        </span>
                      </td>
                      <td className="px-6 py-4 text-slate-600">{formatDateTime(group.updated_at)}</td>
                      <td className="px-6 py-4">
                        <div className="flex justify-end">
                          <ActionMenu
                            group={group}
                            isOpen={openMenuId === group.id}
                            isSending={sendWelcome.isPending || sendPassportLink.isPending}
                            onOpen={() => setOpenMenuId(openMenuId === group.id ? null : group.id)}
                            onClose={() => setOpenMenuId(null)}
                            onWelcome={() => openMessagePreview(group, "welcome")}
                            onPassportLink={() => openMessagePreview(group, "passport_link")}
                          />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {showCreate && (
        <CreateBroadcastDialog
          isLoading={createGroup.isPending}
          onClose={() => setShowCreate(false)}
          onSubmit={async (payload) => {
            await createGroup.mutateAsync(payload);
            setShowCreate(false);
          }}
        />
      )}

      {messageTarget && (
        <MessagePreviewDialog
          group={messageTarget.group}
          messageType={messageTarget.messageType}
          isSending={sendWelcome.isPending || sendPassportLink.isPending}
          onClose={() => setMessageTarget(null)}
          onSend={async ({ passportLink, messageContent }) => {
            const result = messageTarget.messageType === "welcome"
              ? await sendWelcome.mutateAsync({
                  groupId: messageTarget.group.id,
                  messageContent,
                })
              : await sendPassportLink.mutateAsync({
                  groupId: messageTarget.group.id,
                  passportLink,
                  messageContent,
                });
            setLastSend(result);
            if (result.batch_id && typeof window !== "undefined") {
              const savedBatch = { id: result.batch_id, startedAt: Date.now() };
              setPersistedBatch(savedBatch);
              window.sessionStorage.setItem(LAST_BATCH_STORAGE_KEY, JSON.stringify(savedBatch));
            }
            setMessageTarget(null);
          }}
        />
      )}
    </div>
  );
}

function ActionMenu({
  group,
  isOpen,
  isSending,
  onOpen,
  onClose,
  onWelcome,
  onPassportLink,
}: {
  group: WhatsAppBroadcastGroup;
  isOpen: boolean;
  isSending: boolean;
  onOpen: () => void;
  onClose: () => void;
  onWelcome: () => void;
  onPassportLink: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!ref.current?.contains(target) && !menuRef.current?.contains(target)) onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isOpen, onClose]);

  return (
    <div ref={ref} className="relative">
      <button
        ref={buttonRef}
        type="button"
        className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 shadow-sm hover:bg-slate-50"
        onClick={() => {
          const rect = buttonRef.current?.getBoundingClientRect();
          if (rect) {
            const menuWidth = 240;
            const menuHeight = 96;
            const top = rect.bottom + 8 + menuHeight > window.innerHeight
              ? Math.max(8, rect.top - menuHeight - 8)
              : rect.bottom + 8;
            setMenuPosition({
              left: Math.max(8, Math.min(window.innerWidth - menuWidth - 8, rect.right - menuWidth)),
              top,
            });
          }
          onOpen();
        }}
        aria-label={`Open actions for ${group.name}`}
        aria-expanded={isOpen}
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {isOpen && menuPosition && createPortal(
        <div
          ref={menuRef}
          className="fixed z-[70] w-60 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl"
          style={{ left: menuPosition.left, top: menuPosition.top }}
        >
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            disabled={isSending}
            onClick={onWelcome}
          >
            <Send className="h-4 w-4" />
            Welcome message
          </button>
          <button
            type="button"
            className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            disabled={isSending}
            onClick={onPassportLink}
          >
            <Send className="h-4 w-4" />
            Passport link
          </button>
        </div>,
        document.body,
      )}
    </div>
  );
}

function CreateBroadcastDialog({
  isLoading,
  onClose,
  onSubmit,
}: {
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (payload: {
    name: string;
    organizingCompanyName: string;
    contacts: WhatsAppRecipientInput[];
    supportContacts: WhatsAppSupportContactInput[];
    recipientOptInConfirmed: boolean;
    file: File | null;
  }) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [organizingCompanyName, setOrganizingCompanyName] = useState("");
  const [manual, setManual] = useState<ManualContact>({ name: "", phone_number: "" });
  const [contacts, setContacts] = useState<ManualContact[]>([]);
  const [support, setSupport] = useState<ManualContact>({ name: "", phone_number: "" });
  const [supportContacts, setSupportContacts] = useState<ManualContact[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [recipientOptInConfirmed, setRecipientOptInConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    if (!name.trim()) {
      setError("Enter a group name.");
      return;
    }
    if (!organizingCompanyName.trim()) {
      setError("Enter the organising company name.");
      return;
    }
    if (contacts.length === 0 && !file) {
      setError("Add at least one named recipient or upload an Excel file.");
      return;
    }
    if (supportContacts.length === 0) {
      setError("Add at least one customer support contact.");
      return;
    }
    if (!recipientOptInConfirmed) {
      setError("Confirm that recipients agreed to receive trip updates on WhatsApp.");
      return;
    }
    try {
      await onSubmit({
        name: name.trim(),
        organizingCompanyName: organizingCompanyName.trim(),
        contacts,
        supportContacts,
        recipientOptInConfirmed,
        file,
      });
    } catch (submitError) {
      setError(readErrorMessage(submitError, "Could not save this WhatsApp list."));
    }
  };

  return (
    <DialogFrame title="Create WhatsApp Broadcast Group" onClose={onClose}>
      <p className="text-sm text-slate-500">
        Each saved recipient receives a separate WhatsApp message; this does not create a shared WhatsApp chat group.
      </p>
      <form className="mt-5 space-y-5" onSubmit={handleSubmit}>
        <div className="grid gap-4 md:grid-cols-2">
          <Input
            label="Group name"
            hint="This name will be visible to clients inside the message."
            placeholder="Vietnam Leadership Trip 2026"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
          <Input
            label="Organising company name"
            hint="This company name will be visible to clients inside the message."
            placeholder="Bluechip"
            value={organizingCompanyName}
            onChange={(event) => setOrganizingCompanyName(event.target.value)}
            required
          />
        </div>

        <ContactEditor
          title="Recipients"
          description="Names are required because every message is personalised as Dear [Name]."
          value={manual}
          contacts={contacts}
          onValueChange={setManual}
          onAdd={() => addContact(manual, setContacts, setManual, "recipient")}
          onRemove={(index) => setContacts((current) => current.filter((_, itemIndex) => itemIndex !== index))}
        />

        <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-dashed border-slate-300 px-4 py-4 hover:bg-slate-50">
          <span className="flex min-w-0 items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
              <FileSpreadsheet className="h-5 w-5" />
            </span>
            <span className="min-w-0">
              <span className="block truncate font-medium text-slate-900">
                {file ? file.name : "Upload Excel contacts"}
              </span>
              <span className="block text-sm text-slate-500">
                Use .xlsx or .xlsm with name and phone/WhatsApp columns. Bare 10-digit numbers use India (+91); include country codes for all others.
              </span>
            </span>
          </span>
          <Upload className="h-5 w-5 shrink-0 text-slate-400" />
          <input
            type="file"
            accept=".xlsx,.xlsm"
            className="sr-only"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>

        <ContactEditor
          title="Customer support contacts"
          description="Every contact added here appears at the end of both messages. You can add up to three."
          value={support}
          contacts={supportContacts}
          onValueChange={setSupport}
          onAdd={() => {
            if (supportContacts.length >= 3) {
              setError("You can add up to three customer support contacts.");
              return;
            }
            addContact(support, setSupportContacts, setSupport, "support contact");
          }}
          onRemove={(index) => setSupportContacts((current) => current.filter((_, itemIndex) => itemIndex !== index))}
        />

        <label className="flex items-start gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 text-sm text-slate-700">
          <input
            type="checkbox"
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
            checked={recipientOptInConfirmed}
            onChange={(event) => setRecipientOptInConfirmed(event.target.checked)}
          />
          <span>
            I confirm these recipients agreed to receive trip-related WhatsApp updates and can request that messages stop.
          </span>
        </label>

        {error && <ErrorBanner message={error} />}

        <div className="flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>Save List</Button>
        </div>
      </form>
    </DialogFrame>
  );
}

function ContactEditor({
  title,
  description,
  value,
  contacts,
  onValueChange,
  onAdd,
  onRemove,
}: {
  title: string;
  description: string;
  value: ManualContact;
  contacts: ManualContact[];
  onValueChange: React.Dispatch<React.SetStateAction<ManualContact>>;
  onAdd: () => void;
  onRemove: (index: number) => void;
}) {
  return (
    <section className="space-y-3 rounded-xl border border-slate-200 p-4">
      <div>
        <h3 className="font-medium text-slate-900">{title}</h3>
        <p className="mt-1 text-xs text-slate-500">{description}</p>
      </div>
      <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
        <Input
          label="Name"
          placeholder="Raman Jha"
          value={value.name}
          onChange={(event) => onValueChange((current) => ({ ...current, name: event.target.value }))}
        />
        <Input
          label="WhatsApp number"
          placeholder="+91 98187 52221"
          value={value.phone_number}
          onChange={(event) => onValueChange((current) => ({ ...current, phone_number: event.target.value }))}
        />
        <div className="flex items-end">
          <Button type="button" variant="secondary" onClick={onAdd}>Add</Button>
        </div>
      </div>
      {contacts.length > 0 && (
        <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
          {contacts.map((contact, index) => (
            <div key={`${contact.phone_number}-${index}`} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 truncate text-slate-700">
                {contact.name} - {contact.phone_number}
              </span>
              <button type="button" className="text-xs font-medium text-red-600 hover:text-red-700" onClick={() => onRemove(index)}>
                Remove
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function MessagePreviewDialog({
  group,
  messageType,
  isSending,
  onClose,
  onSend,
}: {
  group: WhatsAppBroadcastGroup;
  messageType: WhatsAppMessageType;
  isSending: boolean;
  onClose: () => void;
  onSend: (payload: { passportLink: string; messageContent: string }) => Promise<void>;
}) {
  const { data: detail, isLoading: isLoadingDetail } = useWhatsAppGroup(group.id);
  const previewRequest = usePreviewWhatsAppMessage();
  const [passportLink, setPassportLink] = useState("");
  const [messageContent, setMessageContent] = useState<string | null>(null);
  const [previewRecipientId, setPreviewRecipientId] = useState<string | null>(null);
  const [preview, setPreview] = useState<WhatsAppPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const previewSequence = useRef(0);
  const previewMutate = previewRequest.mutate;

  useEffect(() => {
    const sequence = ++previewSequence.current;
    const timeout = window.setTimeout(() => {
      previewMutate(
        {
          groupId: group.id,
          draft: {
            message_type: messageType,
            passport_link: messageType === "passport_link" ? passportLink : null,
            message_content: messageContent,
            recipient_id: previewRecipientId,
          },
        },
        {
          onSuccess: (response) => {
            if (sequence !== previewSequence.current) return;
            setPreview(response);
            setMessageContent((current) => current ?? response.message_content);
            setError(null);
          },
          onError: (previewError) => {
            if (sequence !== previewSequence.current) return;
            setError(readErrorMessage(previewError, "Could not generate the WhatsApp preview."));
          },
        },
      );
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [group.id, messageContent, messageType, passportLink, previewMutate, previewRecipientId]);

  const resolvedMessageContent = (messageContent ?? preview?.message_content ?? "").trim();
  const canSend = Boolean(
    detail?.recipient_opt_in_confirmed
    && detail.support_contacts.length > 0
    && resolvedMessageContent
    && (messageType === "welcome" || passportLink.trim()),
  );

  const handleSend = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    if (!resolvedMessageContent) {
      setError("Add text before sending. Meta requires this editable template section to contain text.");
      return;
    }
    if (messageType === "passport_link" && !passportLink.trim()) {
      setError("Paste the passport upload link before sending.");
      return;
    }
    try {
      await onSend({
        passportLink: passportLink.trim(),
        messageContent: resolvedMessageContent,
      });
    } catch (sendError) {
      setError(readErrorMessage(sendError, "WhatsApp could not submit this broadcast."));
    }
  };

  return (
    <DialogFrame
      title={messageType === "welcome" ? "Preview Welcome Message" : "Preview Passport Link Message"}
      onClose={onClose}
      widthClass="max-w-5xl"
    >
      <form className="space-y-5" onSubmit={handleSend}>
        <div className="flex gap-3 rounded-xl border border-blue-100 bg-blue-50/60 p-4 text-sm text-blue-900">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            This box supplies Meta Body variable {messageType === "welcome" ? "{{3}}" : "{{4}}"} and can change before each send. The remaining wording is fixed in the approved Meta template; changing that fixed text requires Meta approval again.
          </p>
        </div>

        {messageType === "passport_link" && (
          <Input
            label="Passport upload link"
            hint="This secure link is inserted separately into every recipient's message."
            placeholder="https://..."
            value={passportLink}
            onChange={(event) => setPassportLink(event.target.value)}
            required
          />
        )}

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <label className="block text-sm font-medium text-slate-700">
              Editable message section
              <textarea
                className="mt-1.5 min-h-56 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                value={messageContent ?? preview?.message_content ?? ""}
                onChange={(event) => setMessageContent(event.target.value)}
                maxLength={600}
              />
              {messageContent !== null && !resolvedMessageContent && (
                <span className="mt-1.5 block text-xs font-normal text-amber-700">
                  Add text before sending. Meta requires this editable template section to contain text.
                </span>
              )}
            </label>
            {detail && detail.recipients.length > 1 && (
              <label className="block text-sm font-medium text-slate-700">
                Preview recipient
                <select
                  className="mt-1.5 h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  value={previewRecipientId ?? preview?.recipient_id ?? ""}
                  onChange={(event) => setPreviewRecipientId(event.target.value)}
                >
                  {detail.recipients.map((recipient) => (
                    <option key={recipient.id} value={recipient.id}>
                      {recipient.name || "Guest"} - {recipient.normalized_phone_number}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium text-slate-700">Individual WhatsApp preview</h3>
              <span className="text-xs text-slate-500">
                {preview?.recipient_count ?? group.recipient_count} recipient{group.recipient_count === 1 ? "" : "s"}
              </span>
            </div>
            <div className="mt-1.5 min-h-96 rounded-2xl bg-[#e5ddd5] p-4 shadow-inner">
              <div className="ml-auto max-w-[94%] rounded-xl rounded-tr-sm bg-[#dcf8c6] p-3 text-sm leading-5 text-slate-900 shadow-sm">
                {preview ? (
                  <p className="whitespace-pre-wrap">{preview.rendered_message}</p>
                ) : (
                  <div className="space-y-3 py-2">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-24 w-full" />
                    <Skeleton className="h-16 w-4/5" />
                  </div>
                )}
              </div>
            </div>
            {preview && (
              <p className="mt-2 text-xs text-slate-500">
                Template: {preview.template_name} - Previewing {preview.recipient_name}
              </p>
            )}
          </div>
        </div>

        {isLoadingDetail && <p className="text-sm text-slate-500">Loading recipient and support details...</p>}
        {detail && !detail.recipient_opt_in_confirmed && (
          <ErrorBanner message="This older list has no recorded recipient opt-in confirmation. Create a new list before sending." />
        )}
        {detail && detail.support_contacts.length === 0 && (
          <ErrorBanner message="This older list has no customer support contacts. Create a new list before sending." />
        )}
        {error && <ErrorBanner message={error} />}

        <div className="flex justify-end gap-3">
          <Button type="button" variant="secondary" onClick={onClose} disabled={isSending}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isSending} disabled={!canSend || previewRequest.isPending}>
            <Send className="h-4 w-4" />
            Send individually to {group.recipient_count}
          </Button>
        </div>
      </form>
    </DialogFrame>
  );
}

function DialogFrame({
  title,
  onClose,
  widthClass = "max-w-3xl",
  children,
}: {
  title: string;
  onClose: () => void;
  widthClass?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <Card className={`max-h-[92vh] w-full overflow-auto shadow-2xl ${widthClass}`}>
        <CardContent className="p-6">
          <div className="mb-5 flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
            <button
              type="button"
              className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
              onClick={onClose}
              aria-label="Close dialog"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
          {children}
        </CardContent>
      </Card>
    </div>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{message}</div>;
}

function readErrorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = (error as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) return message;
  }
  return fallback;
}
