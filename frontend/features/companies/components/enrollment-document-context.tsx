import { Input } from "@/components/ui/input";
import { getPassportCountryOptions } from "@/lib/utils/passport-country";

const COUNTRIES = getPassportCountryOptions(3);

export function EnrollmentDocumentContext({ issuer, documentType, confirmed, sourceOpened, disabled, onIssuer, onType, onConfirmed }: {
  issuer: string; documentType: string; confirmed: boolean; sourceOpened: boolean; disabled: boolean;
  onIssuer: (value: string) => void; onType: (value: string) => void; onConfirmed: (value: boolean) => void;
}) {
  return <fieldset disabled={disabled} className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3"><legend className="px-1 text-sm font-semibold text-slate-800">Reviewed document context</legend>
    <p className="text-xs leading-5 text-slate-600">Open the saved submission and inspect its passport image. Read the issuer and document type from that document; nationality and place of issue are not substitutes.</p>
    <label className="block space-y-1.5 text-sm font-medium text-slate-700">Reviewed issuing country<select required value={issuer} onChange={(event) => { onIssuer(event.target.value); onConfirmed(false); }} className="min-h-11 w-full rounded-xl border border-slate-300 bg-white px-3"><option value="">Select the document’s issuing country</option>{COUNTRIES.map((country) => <option key={country.value} value={country.value}>{country.label}</option>)}</select></label>
    <Input label="Reviewed document type" value={documentType} required maxLength={16} onChange={(event) => { onType(event.target.value.toUpperCase()); onConfirmed(false); }} hint="Enter the document type printed in the passport, for example P. No value is selected automatically." />
    <label className="flex items-start gap-3 text-sm leading-6 text-slate-700"><input type="checkbox" required checked={confirmed} onChange={(event) => onConfirmed(event.target.checked)} disabled={!sourceOpened || !issuer || !documentType.trim()} className="mt-1" />I inspected the source passport image and confirm this issuing context.</label>
    {!sourceOpened && <p className="text-xs text-amber-800">Open “Review this saved submission” before confirming the document context.</p>}
  </fieldset>;
}
