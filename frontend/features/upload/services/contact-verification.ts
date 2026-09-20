import { normalizePhoneNumber } from "@/lib/utils/phone-number";

/** Public OTP input requires an explicit country code unless it is a full Indian number. */
export function normalizeOtpPhone(raw: string): string | null {
  const value = raw.trim();
  const digits = value.replace(/\D/g, "");
  if (!value.startsWith("+") && !value.startsWith("00") && digits.length !== 10) return null;
  const phone = normalizePhoneNumber(value);
  if (phone?.startsWith("+91") && phone.length !== 13) return null;
  return phone;
}
