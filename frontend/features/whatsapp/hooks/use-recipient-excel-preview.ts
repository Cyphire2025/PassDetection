"use client";

import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";
import type { ManualContact } from "../types/contacts";
import { readErrorMessage } from "../components/whatsapp-dialog-ui";
import { whatsappApi } from "../api/whatsapp.api";
import {
  mergeRecipientImportRejectedRows,
  mergeRecipientImportMatchingFields,
  mergeRecipientImportPreview,
  type RecipientImportMatchingField,
} from "../utils/recipient-import";
import type { RejectedContactDraft, RecipientImportState } from "../utils/recipient-import-state";

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
  const matchingFieldsRef = useRef<RecipientImportMatchingField[]>([]);
  const omittedRejectedCountsRef = useRef(new Map<string, number>());
  const duplicateSourceFilesRef = useRef(new Map<string, File>());
  const [duplicateSourceFiles, setDuplicateSourceFiles] = useState<File[]>([]);
  const [rejectedContactCount, setRejectedContactCount] = useState(0);
  const [rejectedContacts, setRejectedContacts] = useState<
    RejectedContactDraft[]
  >([]);
  const [importedFieldKeys, setImportedFieldKeys] = useState<string[]>([]);

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

      const hasOmittedRows = Boolean(preview.rejected_rows_truncated || (preview.omitted_rejected_count ?? 0) > 0 || (preview.rejected_count ?? 0) > (preview.rejected_rows?.length ?? 0));
      const sourceKey = `${file.name}:${file.size}:${file.lastModified}`;
      if (hasOmittedRows) {
        if (!preview.rejected_count || preview.rejected_counts?.duplicate_phone !== preview.rejected_count) {
          throw new Error("This preview omits rows that cannot all be safely retained as shared-number records. Correct the invalid rows in the workbook and upload it again, or explicitly ignore this failed import. No rows from this file were added.");
        }
        if (!duplicateSourceFilesRef.current.has(sourceKey) && duplicateSourceFilesRef.current.size >= 10) {
          throw new Error("Save the current imports before adding another large workbook. A save can retain at most 10 original source files. No rows from this file were added.");
        }
      }

      const merged = mergeRecipientImportPreview(
        contactsRef.current,
        preview,
        excludedPhoneNumbersRef.current,
      );
      if (hasOmittedRows) {
        duplicateSourceFilesRef.current.set(sourceKey, file);
        setDuplicateSourceFiles(Array.from(duplicateSourceFilesRef.current.values()));
      }
      contactsRef.current = merged.contacts;
      setContacts(merged.contacts);
      const accumulatedRejectedRows = mergeRecipientImportRejectedRows(
        rejectedContactsRef.current,
        merged.rejectedRows,
        file.name,
      );
      rejectedContactsRef.current = accumulatedRejectedRows;
      const accumulatedMatchingFields = mergeRecipientImportMatchingFields(
        matchingFieldsRef.current,
        merged.availableMatchingFields,
      );
      matchingFieldsRef.current = accumulatedMatchingFields;
      setImportedFieldKeys(accumulatedMatchingFields.map((field) => field.key));
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
      setRejectedContactCount(accumulatedRejectedCount);
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
        matchingFieldCount: accumulatedMatchingFields.length,
        retainedSourceFileCount: duplicateSourceFilesRef.current.size,
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
    matchingFieldsRef.current = [];
    omittedRejectedCountsRef.current.clear();
    duplicateSourceFilesRef.current.clear();
    setDuplicateSourceFiles([]);
    setRejectedContactCount(0);
    setRejectedContacts([]);
    setImportedFieldKeys([]);
    setImportState({ status: "idle" });
  };

  return {
    importState,
    previewFile,
    rejectedContacts,
    rejectedContactCount,
    importedFieldKeys,
    duplicateSourceFiles,
    dismissImportError: () => { if (importState.status === "error") setImportState({ status: "idle" }); },
    resetImport,
  };
}

