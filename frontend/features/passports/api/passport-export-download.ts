import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { capturePrivateOperationOwner } from "@/lib/api/request-owner";
import type { PassportGroupExportCompletion } from "./passport-exports.types";

export async function completePreparedGroupExport(
  groupId: string,
  historyId: string,
  owner = capturePrivateOperationOwner(),
): Promise<PassportGroupExportCompletion> {
  owner.assertCurrent();
  const response = await apiClient.post<PassportGroupExportCompletion>(
    API_ENDPOINTS.passports.groupExportHistoryComplete(groupId, historyId),
    undefined,
    owner.requestConfig,
  );
  owner.assertCurrent();
  return response.data;
}

export async function confirmStartedGroupExport(
  groupId: string,
  historyId: string,
  owner: ReturnType<typeof capturePrivateOperationOwner>,
): Promise<void> {
  try {
    await completePreparedGroupExport(groupId, historyId, owner);
  } catch {
    owner.assertCurrent();
    throw new Error(
      "The file download started, but its history could not be confirmed. "
      + "It will not appear in download history; download again only if the file is missing.",
    );
  }
}

export function requireExportHistoryId(value: unknown): string {
  if (typeof value !== "string" || value.trim().length === 0) {
    throw new Error(
      "The server did not return a download confirmation ID. The file was not started.",
    );
  }
  return value.trim();
}

export function passportImageDownloadFilename(groupName: string) {
  const normalized = groupName
    .normalize("NFKC")
    .replace(/[\\/:*?"<>|\u0000-\u001f\u007f]+/g, "_")
    .replace(/\s+/g, " ")
    .replace(/^[ ._]+|[ ._]+$/g, "")
    .slice(0, 100)
    .replace(/[ .]+$/g, "");
  const reserved = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i.test(normalized)
    ? `_${normalized}`
    : normalized;
  const ascii = (reserved || "GROUP")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^A-Za-z0-9._ -]+/g, "_")
    .replace(/^[ ._]+|[ ._]+$/g, "") || "GROUP";
  return `${ascii.slice(0, 100)}_PASSPORT_IMAGES.zip`;
}
