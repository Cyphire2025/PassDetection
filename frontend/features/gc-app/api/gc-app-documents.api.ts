import apiClient from "@/lib/api/client";
import type { CommonDocumentUpload, GcAppGroupContent, GcCommonDocument } from "../types";
import type { GcMutationRequestConfig, RawCommonDocument } from "./gc-app-wire.types";
import { ROOT, agencyParams } from "./gc-app-transport";
import { normalizeDocument } from "./gc-app-content-mappers";

export const gcAppDocumentsApi = {
  getGroupContent: async (
    agencyId: string | null,
    groupId: string,
    signal?: AbortSignal,
  ): Promise<GcAppGroupContent> => {
    const documents = await apiClient.get<RawCommonDocument[]>(`${ROOT}/groups/${groupId}/common-documents`, {
      params: agencyParams(agencyId),
      signal,
    });
    return {
      common_documents: documents.data.map(normalizeDocument),
      // Announcements have their own paged query; visiting Documents must not
      // fetch the legacy announcement history as an unrelated side effect.
      announcements: [],
    };
  },

  uploadCommonDocument: async (
    agencyId: string | null,
    groupId: string,
    upload: CommonDocumentUpload,
    expectedAccessRevision: number, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcCommonDocument> => {
    const form = new FormData();
    form.append("file", upload.file);
    form.append("display_name", upload.title);
    form.append("category", upload.category);
    form.append("offline_available", "true");
    form.append("expected_access_revision", String(expectedAccessRevision));
    const endpoint = upload.replace_document_id
      ? `${ROOT}/groups/${groupId}/common-documents/${upload.replace_document_id}/replace`
      : `${ROOT}/groups/${groupId}/common-documents`;
    const { data } = await apiClient.post<RawCommonDocument>(
      endpoint,
      form,
      { ...requestConfig,
        params: agencyParams(agencyId),
        // Let the browser generate the multipart boundary. Supplying a bare
        // multipart Content-Type can produce an unparseable or indefinitely
        // pending upload because the boundary is part of that header. The
        // shared API client defaults to JSON, so explicitly clear that default
        // for this FormData request.
        headers: { "Content-Type": null },
        timeout: 120_000,
        onUploadProgress: (event) => {
          const ratio = event.progress
            ?? (event.total && event.total > 0 ? event.loaded / event.total : null);
          if (ratio !== null) {
            upload.onProgress?.(Math.min(100, Math.max(0, Math.round(ratio * 100))));
          }
        },
      },
    );
    return normalizeDocument(data);
  },

  setCommonDocumentPublished: async (
    agencyId: string | null,
    groupId: string,
    documentId: string,
    published: boolean, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcCommonDocument> => {
    const { data } = await apiClient.post<RawCommonDocument>(
      `${ROOT}/groups/${groupId}/common-documents/${documentId}/${published ? "publish" : "unpublish"}`,
      undefined,
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return normalizeDocument(data);
  },

  previewCommonDocument: async (
    agencyId: string | null,
    groupId: string,
    documentId: string,
    signal?: AbortSignal, requestConfig?: GcMutationRequestConfig,
  ): Promise<Blob> => {
    const { data } = await apiClient.get<Blob>(
      `${ROOT}/groups/${groupId}/common-documents/${documentId}/content`,
      { ...requestConfig,
        params: agencyParams(agencyId),
        responseType: "blob",
        signal,
        timeout: 120_000,
      },
    );
    if (!(data instanceof Blob) || data.type.split(";", 1)[0]?.toLowerCase() !== "application/pdf") {
      throw new Error("The common document preview was not a PDF.");
    }
    return data;
  },

  reorderCommonDocuments: async (
    agencyId: string | null,
    groupId: string,
    orderedDocumentIds: string[],
    expectedAccessRevision: number, requestConfig?: GcMutationRequestConfig,
  ): Promise<GcCommonDocument[]> => {
    const { data } = await apiClient.put<RawCommonDocument[]>(
      `${ROOT}/groups/${groupId}/common-documents/reorder`,
      { ordered_document_ids: orderedDocumentIds, expected_access_revision: expectedAccessRevision },
      { ...requestConfig, params: agencyParams(agencyId) },
    );
    return data.map(normalizeDocument);
  },

  deleteCommonDocument: async (
    agencyId: string | null,
    groupId: string,
    documentId: string, requestConfig?: GcMutationRequestConfig,
  ): Promise<void> => {
    await apiClient.delete(`${ROOT}/groups/${groupId}/common-documents/${documentId}`, { ...requestConfig,
      params: agencyParams(agencyId),
    });
  },
};
