"use client";

import { useRef, useState, type FormEvent } from "react";
import { REVIEW_FIELDS } from "@/features/upload/components/upload-flow.constants";
import { cleanPassportReviewFields } from "@/features/passports/utils/passport-review";
import { normalizePhoneNumber } from "@/lib/utils/phone-number";
import { companyPeopleApi } from "../api/company-people.api";
import type { CompanyPersonRecord } from "../types/company-people";
import { companyErrorMessage } from "../utils/company-errors";

export interface CompanyPersonEditorProps {
  agencyId: string;
  companyId: string;
  record: CompanyPersonRecord;
  onSaved: () => Promise<void>;
  onCancel: () => void;
  onBusy: (busy: boolean) => void;
}

/** Edits remain bound to the revision opened, including after background refresh. */
export function useCompanyPersonEditor({ agencyId, companyId, record, onSaved, onBusy }: CompanyPersonEditorProps) {
  const [opened] = useState(record);
  const [name, setName] = useState(record.display_name);
  const [phone, setPhone] = useState(record.phone_number ?? "");
  const [fields, setFields] = useState<Record<string, string>>(() => ({ ...record.current_document?.fields }));
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string>();
  const requestKey = useRef<string | null>(null);
  const saving = useRef(false);
  const phoneValid = !phone.trim() || Boolean(normalizePhoneNumber(phone));
  const fieldsChanged = REVIEW_FIELDS.some((key) => (fields[key] ?? "") !== (opened.current_document?.fields[key] ?? ""));

  function changed() {
    requestKey.current = null;
    setError(undefined);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving.current || !phoneValid || reason.trim().length < 3) return;
    saving.current = true;
    setPending(true);
    onBusy(true);
    setError(undefined);
    requestKey.current ??= crypto.randomUUID();
    try {
      await companyPeopleApi.update(agencyId, companyId, opened.id, {
        expected_revision: opened.revision,
        idempotency_key: requestKey.current,
        reason: reason.trim(),
        display_name: name.trim(),
        phone_number: phone.trim() ? normalizePhoneNumber(phone) : null,
        ...(fieldsChanged ? { fields: cleanPassportReviewFields(fields) } : {}),
      });
      await onSaved();
    } catch (cause) {
      setError(companyErrorMessage(cause, "Changes could not be saved. Close and reopen this record if it has changed."));
    } finally {
      saving.current = false;
      setPending(false);
      onBusy(false);
    }
  }

  return {
    opened, name, setName, phone, setPhone, phoneValid, fields, setFields,
    reason, setReason, pending, error, changed, submit,
    canSave: Boolean(name.trim() && phoneValid && reason.trim().length >= 3),
  };
}
