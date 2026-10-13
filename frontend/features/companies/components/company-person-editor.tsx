"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { REVIEW_FIELDS } from "@/features/upload/components/upload-flow.constants";
import { cleanPassportReviewFields } from "@/features/passports/utils/passport-review";
import { normalizePhoneNumber, PHONE_FORMAT_HELP } from "@/lib/utils/phone-number";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyPersonRecord } from "../types/company-people";
import { CompanyError, companyErrorMessage } from "./company-feedback";
import { CompanyPassportFields } from "./company-passport-fields";

/** Edits are bound to the revision opened by the operator, even after a background refresh. */
export function CompanyPersonEditor({ agencyId, companyId, record, onSaved, onCancel, onBusy }: { agencyId: string; companyId: string; record: CompanyPersonRecord; onSaved: () => Promise<void>; onCancel: () => void; onBusy: (busy: boolean) => void }) {
  const [opened] = useState(record);
  const [name, setName] = useState(record.display_name);
  const [phone, setPhone] = useState(record.phone_number ?? "");
  const [fields, setFields] = useState<Record<string, string>>(() => ({ ...record.current_document?.fields }));
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const requestKey = useRef<string | null>(null);
  const saving = useRef(false);
  const changed = () => { requestKey.current = null; setError(undefined); };
  const phoneValid = !phone.trim() || Boolean(normalizePhoneNumber(phone));
  const fieldsChanged = REVIEW_FIELDS.some((key) => (fields[key] ?? "") !== (opened.current_document?.fields[key] ?? ""));
  return <form className="space-y-5" onSubmit={async (event) => {
    event.preventDefault();
    if (saving.current || !phoneValid || reason.trim().length < 3) return;
    saving.current = true; setPending(true); onBusy(true); setError(undefined);
    requestKey.current ??= crypto.randomUUID();
    try {
      await companyPeopleApi.update(agencyId, companyId, opened.id, { expected_revision: opened.revision, idempotency_key: requestKey.current, reason: reason.trim(), display_name: name.trim(), phone_number: phone.trim() ? normalizePhoneNumber(phone) : null, ...(fieldsChanged ? { fields: cleanPassportReviewFields(fields) } : {}) });
      await onSaved();
    } catch (cause) { setError(companyErrorMessage(cause, "Changes could not be saved. Close and reopen this record if it has changed.")); }
    finally { saving.current = false; setPending(false); onBusy(false); }
  }}>
    <p className="text-xs leading-5 text-slate-500">Updates apply to this person’s current record. Previous trips and document versions stay unchanged.</p>
    <fieldset disabled={pending} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2"><Input label="Full name" required maxLength={120} value={name} onChange={(event) => { changed(); setName(event.target.value); }} /><Input label="Contact number" type="tel" maxLength={32} value={phone} onChange={(event) => { changed(); setPhone(event.target.value); }} hint={PHONE_FORMAT_HELP} error={phoneValid ? undefined : "Enter a valid number including the country code."} /></div>
      {phone !== (opened.phone_number ?? "") && <p className="text-xs leading-5 text-slate-500">A changed number needs the traveller’s verification. Old trip contacts and broadcast recipients stay unchanged.</p>}
      {opened.current_document && <CompanyPassportFields fields={fields} onChange={(key, value) => { changed(); setFields((current) => ({ ...current, [key]: value })); }} />}
      <Input label="Reason for change" required minLength={3} maxLength={500} value={reason} onChange={(event) => { changed(); setReason(event.target.value); }} />
    </fieldset>
    {error && <CompanyError message={error} />}
    <div className="flex flex-wrap justify-end gap-2"><Button type="button" variant="secondary" disabled={pending} onClick={onCancel}>Cancel</Button><Button type="submit" isLoading={pending} disabled={!name.trim() || !phoneValid || reason.trim().length < 3}>Save changes</Button></div>
  </form>;
}
