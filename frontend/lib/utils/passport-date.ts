const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const DISPLAY_DATE_PATTERN = /^(\d{2})\/(\d{2})\/(\d{4})$/;

export function isValidPassportIsoDate(value: string) {
  const match = ISO_DATE_PATTERN.exec(value);
  if (!match) return false;
  return isRealPassportDate(
    Number(match[1]),
    Number(match[2]),
    Number(match[3]),
  );
}

export function formatPassportDateForUi(value: string | null | undefined) {
  if (!value) return "";
  const match = ISO_DATE_PATTERN.exec(value.trim());
  if (!match || !isValidPassportIsoDate(value.trim())) return value.trim();
  return `${match[3]}/${match[2]}/${match[1]}`;
}

export function parsePassportDateFromUi(value: string) {
  const match = DISPLAY_DATE_PATTERN.exec(value.trim());
  if (!match) return null;
  const day = Number(match[1]);
  const month = Number(match[2]);
  const year = Number(match[3]);
  if (!isRealPassportDate(year, month, day)) return null;
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function maskPassportDateForUi(value: string) {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`;
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}`;
}

export function isPassportIsoDateWithinRange(
  value: string,
  minIso?: string,
  maxIso?: string,
) {
  if (!isValidPassportIsoDate(value)) return false;
  if (minIso && value < minIso) return false;
  if (maxIso && value > maxIso) return false;
  return true;
}

export function previousPassportIsoDate(value: string) {
  const match = ISO_DATE_PATTERN.exec(value);
  if (!match || !isValidPassportIsoDate(value)) return null;
  const previous = new Date(Date.UTC(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  ));
  previous.setUTCDate(previous.getUTCDate() - 1);
  return previous.toISOString().slice(0, 10);
}

function isRealPassportDate(year: number, month: number, day: number) {
  if (year < 1900 || year > 2200 || month < 1 || month > 12 || day < 1) {
    return false;
  }
  const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return day <= daysInMonth;
}
