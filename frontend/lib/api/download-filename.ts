// This non-sensitive preference survives auth's passdetection:* storage cleanup.
const DOWNLOAD_SEQUENCE_KEY = "gc-download-sequence:v1";
let lastSequence = 0;

export function safeSuggestedFilename(value: string) {
  return value.trim().replace(/[\\/:*?"<>|\u0000-\u001f\u007f]/g, "_")
    .replace(/[. ]+$/, "") || "download";
}

export function spreadsheetExtension(filename: string) {
  return filename.match(/\.(xlsx|xlsm|xls|csv)$/i)?.[0].toLowerCase();
}

/** Store only a number, never group names, traveller data or local paths. */
export function uniqueSpreadsheetFilename(filename: string) {
  const safe = safeSuggestedFilename(filename);
  const extension = spreadsheetExtension(safe);
  if (!extension) return safe;

  let storedSequence = 0;
  try {
    const stored = Number(window.localStorage.getItem(DOWNLOAD_SEQUENCE_KEY));
    if (Number.isSafeInteger(stored) && stored >= 0 && stored < Number.MAX_SAFE_INTEGER) {
      storedSequence = stored;
    }
  } catch {
    // Private/restricted storage must not prevent saving a spreadsheet.
  }
  lastSequence = Math.max(lastSequence, storedSequence) + 1;
  try {
    window.localStorage.setItem(DOWNLOAD_SEQUENCE_KEY, String(lastSequence));
  } catch {
    // The in-memory counter and timestamp still distinguish subsequent saves.
  }

  const now = new Date();
  const pad = (value: number, digits = 2) => String(value).padStart(digits, "0");
  const date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}-${pad(now.getMilliseconds(), 3)}`;
  const stem = safe.slice(0, -extension.length).slice(0, 140);
  return `${stem}-${date}_${time}-${pad(lastSequence, 4)}${extension}`;
}
