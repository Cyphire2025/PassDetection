export type RecipientImportContact = {
  name: string;
  phone_number: string;
  imported_fields?: Record<string, string>;
};

export type RecipientImportRejectionReasonCode =
  | "missing_phone"
  | "invalid_phone"
  | "missing_name"
  | "duplicate_phone";

export type RecipientImportRejectedRow = {
  sheet_name: string;
  row_number: number;
  raw_name: string | null;
  raw_phone_number: string | null;
  reason_code: RecipientImportRejectionReasonCode;
  reason: string;
  imported_fields?: Record<string, string>;
};

export type RecipientImportRejectedRowWithSource =
  RecipientImportRejectedRow & {
    source_file_name: string;
  };

export type RecipientImportPreview = {
  recipient_count: number;
  accepted_count?: number;
  recipients: RecipientImportContact[];
  rejected_count?: number;
  rejected_rows?: RecipientImportRejectedRow[];
  rejected_rows_truncated?: boolean;
  omitted_rejected_count?: number;
};

export type RecipientImportMergeResult = {
  contacts: RecipientImportContact[];
  addedCount: number;
  duplicateCount: number;
};

export type RecipientImportPreviewMergeResult = RecipientImportMergeResult & {
  acceptedCount: number;
  rejectedCount: number;
  rejectedRows: RecipientImportRejectedRow[];
  rejectedRowsTruncated: boolean;
  omittedRejectedCount: number;
};

/**
 * Mirrors the backend's useful phone-normalization cases closely enough for
 * client-side de-duplication. The backend remains the source of truth.
 */
export function recipientPhoneMergeKey(rawPhoneNumber: string): string | null {
  const value = rawPhoneNumber.trim();
  if (!value) return null;

  const hasPlus = value.startsWith("+");
  const hasInternationalPrefix = value.startsWith("00");
  let digits = value.replace(/\D/g, "");
  if (hasInternationalPrefix) digits = digits.slice(2);
  if (digits.length < 8 || digits.length > 15) {
    return `raw:${value.toLocaleLowerCase()}`;
  }

  if (!hasPlus && !hasInternationalPrefix && digits.length === 10) {
    return `+91${digits}`;
  }
  if ((hasPlus || hasInternationalPrefix || digits.length > 10) && !digits.startsWith("0")) {
    return `+${digits}`;
  }
  return `raw:${value.toLocaleLowerCase()}`;
}

export function mergeRecipientImportContacts(
  existingContacts: RecipientImportContact[],
  importedContacts: RecipientImportContact[],
  excludedPhoneNumbers: string[] = [],
): RecipientImportMergeResult {
  const seen = new Set(
    excludedPhoneNumbers
      .map(recipientPhoneMergeKey)
      .filter((key): key is string => Boolean(key)),
  );
  const contacts: RecipientImportContact[] = [];
  let duplicateCount = 0;

  for (const contact of existingContacts) {
    const cleaned = {
      name: contact.name.trim(),
      phone_number: contact.phone_number.trim(),
      ...(contact.imported_fields
        ? { imported_fields: { ...contact.imported_fields } }
        : {}),
    };
    const key = recipientPhoneMergeKey(cleaned.phone_number);
    if (key && seen.has(key)) {
      duplicateCount += 1;
      continue;
    }
    if (key) seen.add(key);
    contacts.push(cleaned);
  }

  let addedCount = 0;
  for (const contact of importedContacts) {
    const cleaned = {
      name: contact.name.trim(),
      phone_number: contact.phone_number.trim(),
      ...(contact.imported_fields
        ? { imported_fields: { ...contact.imported_fields } }
        : {}),
    };
    const key = recipientPhoneMergeKey(cleaned.phone_number);
    if (!cleaned.name || !key || seen.has(key)) {
      duplicateCount += 1;
      continue;
    }
    seen.add(key);
    contacts.push(cleaned);
    addedCount += 1;
  }

  return { contacts, addedCount, duplicateCount };
}

export function mergeRecipientImportPreview(
  existingContacts: RecipientImportContact[],
  preview: RecipientImportPreview,
  excludedPhoneNumbers: string[] = [],
): RecipientImportPreviewMergeResult {
  const merged = mergeRecipientImportContacts(
    existingContacts,
    preview.recipients,
    excludedPhoneNumbers,
  );
  const rejectedRows = (preview.rejected_rows ?? []).map((row) => ({
    ...row,
    ...(row.imported_fields
      ? { imported_fields: { ...row.imported_fields } }
      : {}),
  }));
  const rejectedCount = preview.rejected_count ?? rejectedRows.length;
  const omittedRejectedCount =
    preview.omitted_rejected_count ??
    Math.max(0, rejectedCount - rejectedRows.length);

  return {
    ...merged,
    // "Accepted" in the UI means accepted into this list, not merely valid in
    // the workbook. Re-uploaded or already-saved phone numbers are therefore
    // excluded from both the added and accepted counts.
    acceptedCount: merged.addedCount,
    rejectedCount,
    rejectedRows,
    rejectedRowsTruncated:
      preview.rejected_rows_truncated ??
      omittedRejectedCount > 0,
    omittedRejectedCount,
  };
}

function rejectedRowWithSourceKey(
  row: RecipientImportRejectedRowWithSource,
): string {
  return JSON.stringify([
    row.source_file_name,
    row.sheet_name,
    row.row_number,
    row.raw_name,
    row.raw_phone_number,
    row.reason_code,
  ]);
}

export function mergeRecipientImportRejectedRows(
  existingRows: RecipientImportRejectedRowWithSource[],
  importedRows: RecipientImportRejectedRow[],
  sourceFileName: string,
): RecipientImportRejectedRowWithSource[] {
  const rowsBySource = new Map(
    existingRows.map((row) => [rejectedRowWithSourceKey(row), { ...row }]),
  );

  for (const row of importedRows) {
    const rowWithSource = {
      ...row,
      source_file_name: sourceFileName,
    };
    rowsBySource.set(rejectedRowWithSourceKey(rowWithSource), rowWithSource);
  }

  return Array.from(rowsBySource.values());
}
