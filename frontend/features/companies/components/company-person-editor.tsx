"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PHONE_FORMAT_HELP } from "@/lib/utils/phone-number";
import { useCompanyPersonEditor, type CompanyPersonEditorProps } from "../hooks/use-company-person-editor";
import { CompanyError } from "./company-feedback";
import { CompanyPassportFields } from "./company-passport-fields";

export function CompanyPersonEditor(props: CompanyPersonEditorProps) {
  const editor = useCompanyPersonEditor(props);
  return <form className="space-y-5" onSubmit={editor.submit}>
    <p className="text-xs leading-5 text-slate-500">Updates apply to this person’s current record. Previous trips and document versions stay unchanged.</p>
    <fieldset disabled={editor.pending} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label="Full name" required maxLength={120} value={editor.name}
          onChange={(event) => { editor.changed(); editor.setName(event.target.value); }} />
        <Input label="Contact number" type="tel" maxLength={32} value={editor.phone} hint={PHONE_FORMAT_HELP}
          onChange={(event) => { editor.changed(); editor.setPhone(event.target.value); }}
          error={editor.phoneValid ? undefined : "Enter a valid number including the country code."} />
      </div>
      {editor.phone !== (editor.opened.phone_number ?? "") && <p className="text-xs leading-5 text-slate-500">
        A changed number needs the traveller’s verification. Old trip contacts and broadcast recipients stay unchanged.
      </p>}
      {editor.opened.current_document && <CompanyPassportFields fields={editor.fields}
        onChange={(key, value) => { editor.changed(); editor.setFields((current) => ({ ...current, [key]: value })); }} />}
      <Input label="Reason for change" required minLength={3} maxLength={500} value={editor.reason}
        onChange={(event) => { editor.changed(); editor.setReason(event.target.value); }} />
    </fieldset>
    {editor.error && <CompanyError message={editor.error} />}
    <div className="flex flex-wrap justify-end gap-2">
      <Button type="button" variant="secondary" disabled={editor.pending} onClick={props.onCancel}>Cancel</Button>
      <Button type="submit" isLoading={editor.pending} disabled={!editor.canSave}>Save changes</Button>
    </div>
  </form>;
}
