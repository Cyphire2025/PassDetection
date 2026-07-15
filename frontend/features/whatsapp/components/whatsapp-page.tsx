"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { CheckCircle2, FileSpreadsheet, Link as LinkIcon, MessageCircle, MoreVertical, Plus, Send, Trash2, Upload, X } from "lucide-react";
import { Badge, Button, Card, CardContent, Input, Skeleton } from "@/components/ui";
import { formatDateTime } from "@/lib/utils/format";
import {
  useCreateWhatsAppGroup,
  useDeleteWhatsAppGroup,
  useSendWhatsAppPassportLink,
  useSendWhatsAppWelcome,
  useWhatsAppGroup,
  useWhatsAppGroups,
} from "../hooks/use-whatsapp";
import type { WhatsAppBroadcastGroup, WhatsAppRecipientInput, WhatsAppSendResponse } from "../api/whatsapp.api";

type ManualContact = {
  name: string;
  phone_number: string;
};

export function WhatsAppPage() {
  const { data: groups = [], isLoading, error } = useWhatsAppGroups();
  const createGroup = useCreateWhatsAppGroup();
  const deleteGroup = useDeleteWhatsAppGroup();
  const sendWelcome = useSendWhatsAppWelcome();
  const sendPassportLink = useSendWhatsAppPassportLink();
  const [showCreate, setShowCreate] = useState(false);
  const [openMenuId, setOpenMenuId] = useState<string | null>(null);
  const [passportTarget, setPassportTarget] = useState<WhatsAppBroadcastGroup | null>(null);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [lastSend, setLastSend] = useState<WhatsAppSendResponse | null>(null);

  const handleWelcome = async (group: WhatsAppBroadcastGroup) => {
    setOpenMenuId(null);
    const result = await sendWelcome.mutateAsync(group.id);
    setLastSend(result);
  };

  const handleDelete = async (group: WhatsAppBroadcastGroup) => {
    setOpenMenuId(null);
    if (!window.confirm(`Delete WhatsApp broadcast group "${group.name}"?`)) return;
    await deleteGroup.mutateAsync(group.id);
    if (selectedGroupId === group.id) setSelectedGroupId(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">WhatsApp</h1>
          <p className="mt-1 text-slate-500">Create broadcast lists and send first-contact passport messages.</p>
        </div>
        <Button type="button" onClick={() => setShowCreate(true)}>
          <Plus className="h-4 w-4" />
          Create
        </Button>
      </div>

      {lastSend && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800">
          <CheckCircle2 className="h-4 w-4" />
          <span>{lastSend.sent} submitted to WhatsApp, {lastSend.failed} failed.</span>
        </div>
      )}

      <Card>
        <CardContent className="p-0">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5">
            <div>
              <h2 className="font-semibold text-slate-900">Broadcast Groups</h2>
              <p className="mt-1 text-sm text-slate-500">Saved WhatsApp recipient lists appear here.</p>
            </div>
            <Badge variant="secondary" className="px-3 py-1">{groups.length} groups</Badge>
          </div>

          {error ? (
            <p className="p-5 text-sm text-red-700">WhatsApp groups could not be loaded.</p>
          ) : isLoading ? (
            <div className="space-y-3 p-5"><Skeleton className="h-20" /><Skeleton className="h-20" /></div>
          ) : groups.length === 0 ? (
            <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
              <span className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 text-blue-700">
                <MessageCircle className="h-6 w-6" />
              </span>
              <h3 className="mt-4 font-semibold text-slate-900">No broadcast groups yet</h3>
              <p className="mt-1 max-w-md text-sm text-slate-500">Create a list manually or upload Excel contacts to send your first WhatsApp message.</p>
            </div>
          ) : (
            <div className="divide-y divide-slate-100">
              {groups.map((group) => (
                <div key={group.id} className="flex flex-wrap items-center justify-between gap-4 px-5 py-4">
                  <button type="button" className="min-w-0 text-left" onClick={() => setSelectedGroupId(group.id)}>
                    <div className="font-semibold text-slate-900">{group.name}</div>
                    <div className="mt-1 text-sm text-slate-500">{group.recipient_count} recipients · Updated {formatDateTime(group.updated_at)}</div>
                  </button>
                  <div className="relative flex items-center gap-2">
                    <Button type="button" variant="secondary" onClick={() => setSelectedGroupId(group.id)}>
                      Open
                    </Button>
                    <ActionMenu
                      group={group}
                      isOpen={openMenuId === group.id}
                      isSending={sendWelcome.isPending || sendPassportLink.isPending}
                      onOpen={() => setOpenMenuId(openMenuId === group.id ? null : group.id)}
                      onClose={() => setOpenMenuId(null)}
                      onWelcome={() => void handleWelcome(group)}
                      onPassportLink={() => {
                        setOpenMenuId(null);
                        setPassportTarget(group);
                      }}
                      onDelete={() => void handleDelete(group)}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {selectedGroupId && (
        <GroupDetail groupId={selectedGroupId} onClose={() => setSelectedGroupId(null)} />
      )}

      {showCreate && (
        <CreateBroadcastDialog
          isLoading={createGroup.isPending}
          onClose={() => setShowCreate(false)}
          onSubmit={async ({ name, contacts, file }) => {
            const created = await createGroup.mutateAsync({ name, contacts, file });
            setShowCreate(false);
            setSelectedGroupId(created.id);
          }}
        />
      )}

      {passportTarget && (
        <PassportLinkDialog
          group={passportTarget}
          isLoading={sendPassportLink.isPending}
          onClose={() => setPassportTarget(null)}
          onSubmit={async (passportLink) => {
            const result = await sendPassportLink.mutateAsync({ groupId: passportTarget.id, passportLink });
            setLastSend(result);
            setPassportTarget(null);
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
  onDelete,
}: {
  group: WhatsAppBroadcastGroup;
  isOpen: boolean;
  isSending: boolean;
  onOpen: () => void;
  onClose: () => void;
  onWelcome: () => void;
  onPassportLink: () => void;
  onDelete: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isOpen, onClose]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
        onClick={onOpen}
        aria-label={`Open actions for ${group.name}`}
      >
        <MoreVertical className="h-4 w-4" />
      </button>
      {isOpen && (
        <div className="absolute right-0 z-20 mt-2 w-60 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
          <button type="button" className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" disabled={isSending} onClick={onWelcome}>
            <Send className="h-4 w-4" />
            Send welcome message
          </button>
          <button type="button" className="flex w-full items-center gap-2 px-4 py-3 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50" disabled={isSending} onClick={onPassportLink}>
            <LinkIcon className="h-4 w-4" />
            Passport link
          </button>
          <button type="button" className="flex w-full items-center gap-2 border-t border-slate-100 px-4 py-3 text-left text-sm font-medium text-red-700 hover:bg-red-50" onClick={onDelete}>
            <Trash2 className="h-4 w-4" />
            Delete list
          </button>
        </div>
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
  onSubmit: (payload: { name: string; contacts: WhatsAppRecipientInput[]; file: File | null }) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [manual, setManual] = useState<ManualContact>({ name: "", phone_number: "" });
  const [contacts, setContacts] = useState<ManualContact[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);

  const addManualContact = () => {
    setError(null);
    if (!manual.phone_number.trim()) {
      setError("Enter a WhatsApp number before adding.");
      return;
    }
    setContacts((current) => [...current, { name: manual.name.trim(), phone_number: manual.phone_number.trim() }]);
    setManual({ name: "", phone_number: "" });
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Enter a broadcast group name.");
      return;
    }
    if (contacts.length === 0 && !file) {
      setError("Add at least one number manually or upload an Excel file.");
      return;
    }
    try {
      await onSubmit({ name: name.trim(), contacts, file });
    } catch {
      setError("Could not create WhatsApp group. Check the Excel file and phone numbers.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <Card className="max-h-[90vh] w-full max-w-3xl overflow-auto shadow-2xl">
        <CardContent className="space-y-5 p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Create WhatsApp Broadcast Group</h2>
              <p className="mt-1 text-sm text-slate-500">Add numbers manually or upload Excel. Only name and phone columns are saved.</p>
            </div>
            <button type="button" className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose}>
              <X className="h-5 w-5" />
            </button>
          </div>

          <form className="space-y-5" onSubmit={handleSubmit}>
            <Input label="Group name" placeholder="Thailand 2026" value={name} onChange={(event) => setName(event.target.value)} required />

            <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
              <Input label="Name optional" placeholder="Nipun Vashistha" value={manual.name} onChange={(event) => setManual((current) => ({ ...current, name: event.target.value }))} />
              <Input label="WhatsApp number" placeholder="+91 98765 43210" value={manual.phone_number} onChange={(event) => setManual((current) => ({ ...current, phone_number: event.target.value }))} />
              <div className="flex items-end">
                <Button type="button" variant="secondary" onClick={addManualContact}>Add</Button>
              </div>
            </div>

            {contacts.length > 0 && (
              <div className="rounded-xl border border-slate-200">
                <div className="border-b border-slate-100 px-4 py-2 text-sm font-medium text-slate-700">{contacts.length} manually added</div>
                <div className="max-h-44 divide-y divide-slate-100 overflow-auto">
                  {contacts.map((contact, index) => (
                    <div key={`${contact.phone_number}-${index}`} className="flex items-center justify-between gap-3 px-4 py-2 text-sm">
                      <span className="min-w-0 truncate text-slate-700">{contact.name || "No name"} · {contact.phone_number}</span>
                      <button type="button" className="text-red-600 hover:text-red-700" onClick={() => setContacts((current) => current.filter((_, itemIndex) => itemIndex !== index))}>
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <label className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border border-dashed border-slate-300 px-4 py-4 hover:bg-slate-50">
              <span className="flex min-w-0 items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                  <FileSpreadsheet className="h-5 w-5" />
                </span>
                <span className="min-w-0">
                  <span className="block font-medium text-slate-900">{file ? file.name : "Upload Excel contacts"}</span>
                  <span className="block text-sm text-slate-500">Excel can contain many fields; only names and phone numbers are extracted.</span>
                </span>
              </span>
              <Upload className="h-5 w-5 text-slate-400" />
              <input type="file" accept=".xlsx,.xlsm,.xls" className="sr-only" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
            </label>

            {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

            <div className="flex justify-end gap-3">
              <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>Cancel</Button>
              <Button type="submit" isLoading={isLoading}>Save List</Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function PassportLinkDialog({
  group,
  isLoading,
  onClose,
  onSubmit,
}: {
  group: WhatsAppBroadcastGroup;
  isLoading: boolean;
  onClose: () => void;
  onSubmit: (passportLink: string) => Promise<void>;
}) {
  const [passportLink, setPassportLink] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    if (!passportLink.trim()) {
      setError("Paste the passport upload link.");
      return;
    }
    try {
      await onSubmit(passportLink.trim());
    } catch {
      setError("Could not send passport link messages.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <Card className="w-full max-w-xl shadow-2xl">
        <CardContent className="space-y-5 p-6">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Send Passport Link</h2>
              <p className="mt-1 text-sm text-slate-500">Paste the upload link for {group.name}. The message will be personalized with each saved name.</p>
            </div>
            <button type="button" className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={onClose}>
              <X className="h-5 w-5" />
            </button>
          </div>
          <form className="space-y-4" onSubmit={handleSubmit}>
            <Input label="Passport upload link" placeholder="https://..." value={passportLink} onChange={(event) => setPassportLink(event.target.value)} required />
            {error && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}
            <div className="flex justify-end gap-3">
              <Button type="button" variant="secondary" onClick={onClose} disabled={isLoading}>Cancel</Button>
              <Button type="submit" isLoading={isLoading}>
                <Send className="h-4 w-4" />
                Send
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

function GroupDetail({ groupId, onClose }: { groupId: string; onClose: () => void }) {
  const { data: group, isLoading } = useWhatsAppGroup(groupId);
  return (
    <Card>
      <CardContent className="p-0">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-5">
          <div>
            <h2 className="font-semibold text-slate-900">{group?.name ?? "Broadcast Group"}</h2>
            <p className="mt-1 text-sm text-slate-500">{group?.recipient_count ?? 0} recipients saved.</p>
          </div>
          <Button type="button" variant="secondary" onClick={onClose}>Close</Button>
        </div>
        {isLoading ? (
          <div className="space-y-3 p-5"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase text-slate-500">
                <tr><th className="px-5 py-3">Name</th><th className="px-5 py-3">Original number</th><th className="px-5 py-3">WhatsApp number</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(group?.recipients ?? []).map((recipient) => (
                  <tr key={recipient.id}>
                    <td className="px-5 py-3 font-medium text-slate-900">{recipient.name || "No name"}</td>
                    <td className="px-5 py-3 text-slate-600">{recipient.phone_number}</td>
                    <td className="px-5 py-3 text-slate-600">{recipient.normalized_phone_number}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
