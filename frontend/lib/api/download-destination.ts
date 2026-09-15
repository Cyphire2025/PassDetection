import {
  safeSuggestedFilename,
  spreadsheetExtension,
  uniqueSpreadsheetFilename,
} from "./download-filename";

export interface FileDownloadWritable {
  write(data: Uint8Array): Promise<void>;
  close(): Promise<void>;
  abort?(reason?: unknown): Promise<void>;
}

interface FileDownloadHandle {
  name?: string;
  createWritable(): Promise<FileDownloadWritable>;
}

interface SaveFilePickerOptions {
  suggestedName: string;
  id?: string;
  types?: Array<{ description: string; accept: Record<string, string[]> }>;
}

interface FilePickerWindow extends Window {
  showSaveFilePicker?: (options: SaveFilePickerOptions) => Promise<FileDownloadHandle>;
}

export function isDownloadCancelled(error: unknown): boolean {
  return typeof error === "object" && error !== null
    && "name" in error && error.name === "AbortError";
}

/** Called before the first network request, while the download click is active. */
export async function chooseDownloadDestination(suggestedFilename: string) {
  const filename = uniqueSpreadsheetFilename(suggestedFilename);
  const extension = spreadsheetExtension(filename);
  const picker = typeof window === "undefined"
    ? undefined : (window as FilePickerWindow).showSaveFilePicker;

  if (picker) {
    const fileHandle = await picker.call(window, {
      suggestedName: filename,
      ...(extension ? {
        id: "spreadsheet-exports",
        types: [{
          description: extension === ".csv" ? "CSV spreadsheet" : "Excel workbook",
          accept: { [spreadsheetMimeType(extension)]: [extension] },
        }],
      } : {}),
    });
    return { fileHandle, filename: fileHandle.name ?? filename, useChosenFilename: Boolean(extension || fileHandle.name) };
  }

  if (extension && typeof window !== "undefined") {
    const entered = window.prompt(
      "Save spreadsheet — enter a filename.\n\n"
      + "This browser cannot open the system Save As dialog here. "
      + "To choose a folder, enable ‘Ask where to save each file before downloading’ "
      + "in your browser's Downloads settings, or open this site in Chrome or Edge over HTTPS.",
      filename,
    );
    if (entered === null) throw new DOMException("Download cancelled", "AbortError");
    const renamed = safeSuggestedFilename(entered.trim() || filename);
    return {
      fileHandle: null,
      filename: renamed.toLowerCase().endsWith(extension) ? renamed : `${renamed}${extension}`,
      useChosenFilename: true,
    };
  }

  return { fileHandle: null, filename, useChosenFilename: false };
}

function spreadsheetMimeType(extension: string) {
  if (extension === ".csv") return "text/csv";
  if (extension === ".xls") return "application/vnd.ms-excel";
  if (extension === ".xlsm") return "application/vnd.ms-excel.sheet.macroEnabled.12";
  return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
}
