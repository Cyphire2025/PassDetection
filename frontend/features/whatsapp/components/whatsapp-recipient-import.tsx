"use client";

import {
  AlertTriangle,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
  Upload,
} from "lucide-react";
import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import {
  type ManualContact,
  readErrorMessage,
} from "./whatsapp-dialog-ui";
import {
  whatsappApi,
  type WhatsAppRejectedContactInput,
} from "../api/whatsapp.api";
import {
  mergeRecipientImportRejectedRows,
  mergeRecipientImportPreview,
  type RecipientImportRejectedRowWithSource,
} from "../utils/recipient-import";

export type RejectedContactDraft = RecipientImportRejectedRowWithSource;

export function toRejectedContactInputs(
  contacts: RejectedContactDraft[],
): WhatsAppRejectedContactInput[] {
  return contacts.map((contact) => ({
    source_file_name: contact.source_file_name,
    sheet_name: contact.sheet_name,
    row_number: contact.row_number,
    raw_name: contact.raw_name,
    raw_phone_number: contact.raw_phone_number,
    reason_code: contact.reason_code,
    imported_fields: contact.imported_fields,
  }));
}

export type RecipientImportState =
  | { status: "idle" }
  | { status: "loading"; fileName: string }
  | {
      status: "success";
      fileName: string;
      acceptedCount: number;
      addedCount: number;
      duplicateCount: number;
      rejectedCount: number;
      rejectedRows: RejectedContactDraft[];
      rejectedRowsTruncated: boolean;
      omittedRejectedCount: number;
    }
  | { status: "error"; fileName: string; message: string };

export function useRecipientExcelPreview({
  contacts,
  setContacts,
  excludedPhoneNumbers = [],
  onStart,
}: {
  contacts: ManualContact[];
  setContacts: Dispatch<SetStateAction<ManualContact[]>>;
  excludedPhoneNumbers?: string[];
  onStart: () => void;
}) {
  const [importState, setImportState] = useState<RecipientImportState>({
    status: "idle",
  });
  const requestIdRef = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const contactsRef = useRef(contacts);
  const excludedPhoneNumbersRef = useRef(excludedPhoneNumbers);
  const rejectedContactsRef = useRef<RejectedContactDraft[]>([]);
  const omittedRejectedCountsRef = useRef(new Map<string, number>());
  const [rejectedContacts, setRejectedContacts] = useState<
    RejectedContactDraft[]
  >([]);

  useEffect(() => {
    contactsRef.current = contacts;
  }, [contacts]);

  useEffect(() => {
    excludedPhoneNumbersRef.current = excludedPhoneNumbers;
  }, [excludedPhoneNumbers]);

  useEffect(
    () => () => {
      requestIdRef.current += 1;
      controllerRef.current?.abort();
    },
    [],
  );

  const previewFile = async (file: File) => {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    onStart();
    setImportState({ status: "loading", fileName: file.name });

    try {
      const preview = await whatsappApi.previewContacts(file, controller.signal);
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;

      const merged = mergeRecipientImportPreview(
        contactsRef.current,
        preview,
        excludedPhoneNumbersRef.current,
      );
      contactsRef.current = merged.contacts;
      setContacts(merged.contacts);
      const accumulatedRejectedRows = mergeRecipientImportRejectedRows(
        rejectedContactsRef.current,
        merged.rejectedRows,
        file.name,
      );
      rejectedContactsRef.current = accumulatedRejectedRows;
      omittedRejectedCountsRef.current.set(
        file.name,
        merged.omittedRejectedCount,
      );
      const accumulatedOmittedRejectedCount = Array.from(
        omittedRejectedCountsRef.current.values(),
      ).reduce(
        (total, omittedCount) => total + omittedCount,
        0,
      );
      const accumulatedRejectedCount =
        accumulatedRejectedRows.length + accumulatedOmittedRejectedCount;
      setRejectedContacts(accumulatedRejectedRows);
      setImportState({
        status: "success",
        fileName: file.name,
        acceptedCount: merged.acceptedCount,
        addedCount: merged.addedCount,
        duplicateCount: merged.duplicateCount,
        rejectedCount: accumulatedRejectedCount,
        rejectedRows: accumulatedRejectedRows,
        rejectedRowsTruncated: accumulatedOmittedRejectedCount > 0,
        omittedRejectedCount: accumulatedOmittedRejectedCount,
      });
    } catch (previewError) {
      if (requestId !== requestIdRef.current || controller.signal.aborted) return;
      setImportState({
        status: "error",
        fileName: file.name,
        message: readErrorMessage(
          previewError,
          "The Excel contacts could not be read. Check the columns and try again.",
        ),
      });
    } finally {
      if (requestId === requestIdRef.current) controllerRef.current = null;
    }
  };

  const resetImport = () => {
    requestIdRef.current += 1;
    controllerRef.current?.abort();
    controllerRef.current = null;
    rejectedContactsRef.current = [];
    omittedRejectedCountsRef.current.clear();
    setRejectedContacts([]);
    setImportState({ status: "idle" });
  };

  return { importState, previewFile, rejectedContacts, resetImport };
}

export function ExcelRecipientImport({
  state,
  onFile,
  label,
}: {
  state: RecipientImportState;
  onFile: (file: File) => Promise<void>;
  label: string;
}) {
  const isLoading = state.status === "loading";
  const fileName = state.status === "idle" ? null : state.fileName;
  const rejectionTitleId = useId();

  return (
    <div className="space-y-2">
      <label
        className={`flex items-center justify-between gap-4 rounded-xl border border-dashed px-4 py-4 ${
          isLoading
            ? "cursor-wait border-blue-300 bg-blue-50/60"
            : "cursor-pointer border-slate-300 bg-white hover:bg-slate-50"
        }`}
      >
        <span className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
            {isLoading ? (
              <Loader2 className="h-5 w-5 animate-spin" />
            ) : state.status === "success" && state.rejectedCount > 0 ? (
              <AlertTriangle className="h-5 w-5 text-amber-600" />
            ) : state.status === "success" ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            ) : (
              <FileSpreadsheet className="h-5 w-5" />
            )}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-medium text-slate-900">
              {fileName ?? label}
            </span>
            <span className="block text-sm text-slate-500">
              {isLoading
                ? "Reading and validating recipients..."
                : "Use .xlsx or .xlsm with name and phone/WhatsApp columns."}
            </span>
          </span>
        </span>
        <Upload className="h-5 w-5 shrink-0 text-slate-400" />
        <input
          type="file"
          accept=".xlsx,.xlsm"
          className="sr-only"
          disabled={isLoading}
          onChange={(event) => {
            const selectedFile = event.currentTarget.files?.[0] ?? null;
            event.currentTarget.value = "";
            if (selectedFile) void onFile(selectedFile);
          }}
        />
      </label>

      <div>
        {state.status === "success" && (
          <div className="space-y-3">
            <p
              role="status"
              className={`text-sm ${
                state.rejectedCount > 0
                  ? "text-amber-800"
                  : "text-emerald-700"
              }`}
            >
              {state.addedCount} new recipient
              {state.addedCount === 1 ? "" : "s"} added.
              {state.duplicateCount > 0
                ? ` ${state.duplicateCount} contact${state.duplicateCount === 1 ? " was" : "s were"} skipped because the number is already in this list or broadcast.`
                : " You can edit or remove the accepted recipients above before saving."}
            </p>
            {state.rejectedCount > 0 && (
              <section
                className="rounded-xl border border-amber-200 bg-amber-50/60 p-3"
                aria-labelledby={rejectionTitleId}
              >
                <h4
                  id={rejectionTitleId}
                  className="font-semibold text-amber-900"
                >
                  {state.rejectedCount} spreadsheet row
                  {state.rejectedCount === 1 ? "" : "s"} need attention
                </h4>
                <p className="mt-1 text-xs text-amber-800">
                  Valid recipients were kept. The rows shown below will be
                  saved with this broadcast for correction, but they cannot
                  receive messages.
                  {state.rejectedRowsTruncated &&
                    ` ${state.omittedRejectedCount} additional rejected row${state.omittedRejectedCount === 1 ? " was" : "s were"} counted but could not be included in this preview.`}
                </p>
                {state.rejectedRows.length > 0 && (
                  <div
                    className="mt-3 space-y-2"
                    aria-label="Rejected spreadsheet rows"
                  >
                    {state.rejectedRows.map((row, index) => (
                      <article
                        key={`${row.source_file_name}:${row.sheet_name}:${row.row_number}:${index}`}
                        className="rounded-lg border border-amber-200 bg-white p-3 text-xs text-slate-700"
                      >
                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                          <div className="min-w-0">
                            <span className="font-semibold text-amber-900">Source</span>
                            <p className="break-words">{row.source_file_name}</p>
                          </div>
                          <div>
                            <span className="font-semibold text-amber-900">Sheet and row</span>
                            <p>{row.sheet_name}, row {row.row_number}</p>
                          </div>
                          <div className="min-w-0">
                            <span className="font-semibold text-amber-900">Entered name</span>
                            <p className="break-words">{row.raw_name?.trim() || "Blank"}</p>
                          </div>
                          <div className="min-w-0">
                            <span className="font-semibold text-amber-900">Entered phone</span>
                            <p className="break-all font-mono">{row.raw_phone_number?.trim() || "Blank"}</p>
                          </div>
                        </div>
                        <p className="mt-3 break-words text-amber-900">{row.reason}</p>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            )}
          </div>
        )}
        {state.status === "error" && (
          <p role="alert" className="text-sm text-red-700">
            {state.message}
          </p>
        )}
      </div>
    </div>
  );
}
