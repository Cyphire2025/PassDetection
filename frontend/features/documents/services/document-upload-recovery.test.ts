import { beforeEach, describe, expect, it } from "vitest";
import type { DocumentVerificationResult } from "@/types/document-distribution.types";
import type { DocumentStagingManifest } from "./document-upload-batching";
import {
  clearDocumentUploadRecovery,
  persistDocumentUploadRecovery,
  readDocumentUploadRecovery,
} from "./document-upload-recovery";

const GROUP_ID = "11111111-1111-4111-8111-111111111111";
const DOCUMENT_TYPE = "visa" as const;

function verification(): DocumentVerificationResult {
  return {
    group_id: GROUP_ID,
    document_type: DOCUMENT_TYPE,
    total_count: 1,
    accepted_count: 1,
    rejected_count: 0,
    files: [{
      filename: "visa.pdf",
      detected_type: "visa",
      accepted: true,
      reason: "Matched",
      matched_passenger_id: "passenger-1",
      matched_passenger_name: "Passenger One",
      matched_passenger_ids: ["passenger-1"],
      matched_passenger_names: ["Passenger One"],
      match_confidence: 0.99,
      match_status: "matched",
      match_reason: "Matched",
      staging_receipt: "must-not-enter-react-verification-state",
    }],
  };
}

function manifest(): DocumentStagingManifest {
  return {
    version: 1,
    uploadId: "22222222-2222-4222-8222-222222222222",
    chunks: [{
      chunkId: "33333333-3333-4333-8333-333333333333",
      receipts: ["opaque-receipt"],
      fileCount: 1,
      totalBytes: 1_024,
    }],
    totalFiles: 1,
    totalBytes: 1_024,
    completedChunks: 0,
    createdAt: new Date().toISOString(),
  };
}

describe("document upload recovery", () => {
  beforeEach(() => window.sessionStorage.clear());

  it("restores a receipt manifest without putting receipts in verification metadata", () => {
    expect(persistDocumentUploadRecovery(GROUP_ID, DOCUMENT_TYPE, {
      verification: verification(),
      manifest: manifest(),
    })).toBe(true);

    const recovered = readDocumentUploadRecovery(GROUP_ID, DOCUMENT_TYPE);
    expect(recovered?.manifest.chunks[0].receipts).toEqual(["opaque-receipt"]);
    expect(recovered?.verification.files[0].staging_receipt).toBeNull();
    expect(JSON.stringify(recovered)).not.toContain("must-not-enter-react-verification-state");
  });

  it("removes the recovery manifest after the final chunk acknowledgement", () => {
    const completed = manifest();
    completed.completedChunks = completed.chunks.length;
    completed.chunks[0].receipts = [];

    expect(persistDocumentUploadRecovery(GROUP_ID, DOCUMENT_TYPE, {
      verification: verification(),
      manifest: completed,
    })).toBe(true);
    expect(readDocumentUploadRecovery(GROUP_ID, DOCUMENT_TYPE)).toBeNull();
  });

  it("rejects tampered receipt counts and clears the unusable snapshot", () => {
    const tampered = manifest();
    tampered.chunks[0].fileCount = 2;
    window.sessionStorage.setItem(
      `passdetection:document-staging-manifest:${GROUP_ID}:${DOCUMENT_TYPE}`,
      JSON.stringify({
        version: 1,
        groupId: GROUP_ID,
        documentType: DOCUMENT_TYPE,
        manifest: tampered,
        verification: verification(),
      }),
    );

    expect(readDocumentUploadRecovery(GROUP_ID, DOCUMENT_TYPE)).toBeNull();
    expect(window.sessionStorage.length).toBe(0);
  });

  it("supports explicit cleanup when a selection or incomplete upload is discarded", () => {
    persistDocumentUploadRecovery(GROUP_ID, DOCUMENT_TYPE, {
      verification: verification(),
      manifest: manifest(),
    });
    clearDocumentUploadRecovery(GROUP_ID, DOCUMENT_TYPE);
    expect(readDocumentUploadRecovery(GROUP_ID, DOCUMENT_TYPE)).toBeNull();
  });
});
