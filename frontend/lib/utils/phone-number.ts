/** Match the backend's canonical WhatsApp format; this cannot check membership. */
export function normalizePhoneNumber(raw: string | null | undefined): string | null {
  const value = (raw ?? "").trim();
  if (!value || value.length > 64 || !/^(?:\+|00)?[\d\s().-]+$/.test(value)) return null;
  let digits = value.replace(/\D/g, "");
  if (value.startsWith("00")) digits = digits.slice(2);
  if (digits.length < 8 || digits.length > 15) return null;
  if (value.startsWith("+") || value.startsWith("00") || digits.length > 10) {
    return digits.startsWith("0") ? null : `+${digits}`;
  }
  return digits.length === 10 ? `+91${digits}` : null;
}

export const PHONE_FORMAT_HELP = "Enter a 10-digit Indian number, or an international number with its country code (for example +44 7700 900123).";
