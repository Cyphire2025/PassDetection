import apiClient from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { DistributionDocumentType, DocumentVerificationResult, VerifiedDistributedDocument } from "@/types/document-distribution.types";
import {
  createDocumentStagingManifest,
  createDocumentVerificationSession,
  isPassengerMatchedVerificationFile,
  MAX_DOCUMENT_VERIFICATION_CONCURRENCY,
  runConcurrentDocumentVerification,
  type DocumentUploadProgress,
  type DocumentFilenameReplacement
} from "../services/document-upload-batching";
import { verificationWithoutStagingReceipts } from "../services/document-upload-recovery";
import type { DocumentManualReviewCandidate } from "../services/document-manual-review";
import { attachFilenameReplacements, indexFirstFilenameReplacements } from "../services/document-filename-replacements";
import type { DocumentVerificationUploadPlan } from "./document-distribution.types";

export const documentVerificationApi = {
  verifyDocuments: async (
    groupId: string,
    documentType: DistributionDocumentType,
    files: File[],
    onProgress?: (progress: DocumentUploadProgress) => void,
    signal?: AbortSignal,
    filenameReplacements: DocumentFilenameReplacement[] = [],
  ): Promise<DocumentVerificationUploadPlan> => {
    const session = createDocumentVerificationSession(files);
    const firstReplacementByFilename = indexFirstFilenameReplacements(filenameReplacements);
    const manualReviewByChunk: DocumentManualReviewCandidate[][] = [];
    let fileOffset = 0;
    const fileOffsets = session.chunks.map((chunk) => {
      const offset = fileOffset;
      fileOffset += chunk.length;
      return offset;
    });
    const completedResults = await runConcurrentDocumentVerification({
      session,
      concurrency: MAX_DOCUMENT_VERIFICATION_CONCURRENCY,
      onProgress,
      signal,
      uploadChunk: async (chunk, chunkIndex, reportUpload) => {
        const formData = new FormData();
        formData.append("upload_id", session.uploadId);
        formData.append("chunk_id", session.chunkIds[chunkIndex]);
        chunk.forEach((file) => formData.append("files", file));
        const { data } = await apiClient.post<DocumentVerificationResult>(
          API_ENDPOINTS.documents.verify(groupId, documentType),
          formData,
          {
            headers: { "Content-Type": "multipart/form-data" },
            timeout: 240_000,
            signal,
            onUploadProgress: (event) => reportUpload(event.loaded, event.total),
          },
        );
        if (data.files.length !== chunk.length) {
          throw new Error("The document verification response did not match the selected PDFs.");
        }
        manualReviewByChunk[chunkIndex] = data.files.flatMap((result, index) =>
          !result.accepted && result.manual_review_token
            ? [{
              fileIndex: fileOffsets[chunkIndex] + index,
              file: chunk[index],
              approvalToken: result.manual_review_token,
              uploadId: session.uploadId,
              chunkId: crypto.randomUUID(),
              filenameReplacement: firstReplacementByFilename.get(result.filename),
            }]
            : [],
        );
        return data;
      },
    });
    const normalizedResults = completedResults.map((result) => {
      const verifiedFiles = result.files.map((file) => {
        const accepted = isPassengerMatchedVerificationFile(file);
        if (accepted === file.accepted) return file;
        return {
          ...file,
          accepted,
          reason: file.match_reason || "No passenger match found",
          staging_receipt: null,
        };
      });
      const acceptedCount = verifiedFiles.filter((file) => file.accepted).length;
      return {
        ...result,
        accepted_count: acceptedCount,
        rejected_count: verifiedFiles.length - acceptedCount,
        files: verifiedFiles,
      };
    });
    const stagingManifest = createDocumentStagingManifest(
      session,
      normalizedResults.map((result) => result.files.map((file) => file.accepted)),
      normalizedResults.map((result) =>
        result.files.map((file) => file.staging_receipt),
      ),
    );
    attachFilenameReplacements(stagingManifest, session.chunkIds, normalizedResults, filenameReplacements);
    const verification = verificationWithoutStagingReceipts({
      group_id: groupId,
      document_type: documentType,
      total_count: normalizedResults.reduce(
        (total, result) => total + result.total_count,
        0,
      ),
      accepted_count: normalizedResults.reduce(
        (total, result) => total + result.accepted_count,
        0,
      ),
      rejected_count: normalizedResults.reduce(
        (total, result) => total + result.rejected_count,
        0,
      ),
      files: normalizedResults.flatMap((result) => result.files),
    });
    return {
      stagingManifest,
      verification,
      manualReviewCandidates: manualReviewByChunk.flat(),
    };
  },

  manuallyVerifyDocument: async (
    groupId: string,
    documentType: DistributionDocumentType,
    candidate: DocumentManualReviewCandidate,
    signal?: AbortSignal,
    targetUploadId?: string,
  ): Promise<VerifiedDistributedDocument> => {
    const formData = new FormData();
    formData.append("file", candidate.file);
    formData.append("approval_token", candidate.approvalToken);
    formData.append("upload_id", candidate.uploadId);
    formData.append("chunk_id", candidate.chunkId);
    formData.append("confirmed", "true");
    if (targetUploadId) formData.append("target_upload_id", targetUploadId);
    const { data } = await apiClient.post<VerifiedDistributedDocument>(
      API_ENDPOINTS.documents.manualVerify(groupId, documentType),
      formData,
      {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 240_000,
        signal,
      },
    );
    return data;
  },
};
