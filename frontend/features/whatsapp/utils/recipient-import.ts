export type RecipientImportContact = {
  name: string;
  phone_number: string;
  imported_fields?: Record<string, string>;
};

export type RecipientImportMergeResult = {
  contacts: RecipientImportContact[];
  addedCount: number;
  duplicateCount: number;
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
