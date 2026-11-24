import { Input } from "@/components/ui/input";
import { getPassportCountryOptions } from "@/lib/utils/passport-country";
import type { CompanyDocumentUploadController } from "../../hooks/use-company-document-upload";
import { CompanyPassportFields } from "../company-passport-fields";

const COUNTRIES = getPassportCountryOptions(3);
const LEGACY_COUNTRIES = [{ value: "UNK", label: "Not recorded" }, ...COUNTRIES];

export function DocumentUploadReview({ controller }: { controller: CompanyDocumentUploadController }) {
  const { opened, draft, change, confirmed, setConfirmed } = controller;
  const countries = opened.current_document?.issuing_country === "UNK" ? LEGACY_COUNTRIES : COUNTRIES;
  return <>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block space-y-1.5 text-sm font-medium text-slate-700">
        Issuing country
        <select required value={draft.issuer} onChange={(event) => change("issuer", event.target.value)}
          className="min-h-11 w-full rounded-lg border border-slate-300 bg-white px-3">
          <option value="">Select country</option>
          {countries.map((country) => <option key={country.value} value={country.value}>{country.label}</option>)}
        </select>
      </label>
      <Input label="Document type" required maxLength={16} value={draft.documentType}
        onChange={(event) => change("documentType", event.target.value)} />
    </div>
    <CompanyPassportFields fields={draft.fields} onChange={controller.changeField} />
    <Input label="Reason for document update" required minLength={3} maxLength={500} value={draft.reason}
      onChange={(event) => change("reason", event.target.value)} />
    <label className="flex items-start gap-3 text-sm leading-6 text-slate-700">
      <input type="checkbox" className="mt-1" checked={confirmed}
        onChange={(event) => setConfirmed(event.target.checked)} required />
      I checked this image and the passport details for this person.
    </label>
  </>;
}
