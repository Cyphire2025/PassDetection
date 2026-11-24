import { AxiosError, type AxiosAdapter } from "axios";
import type { OwnerBoundRequestConfig } from "@/lib/api/request-owner";
import type { DocumentBatchReview } from "@/types/document-distribution.types";

export type DocumentOperationMode = "discard" | "manual" | "manual-error" | "verify" | "manual-review";
const batches = ["synthetic-upload-a", "synthetic-upload-b"];

/** In-memory synthetic transport; real client interceptors remain outside it. */
export function createDocumentOperationTransport(operation: DocumentOperationMode, groupId: string) {
  const manualVerificationGate = Promise.withResolvers<void>();
  const writes: Array<{
    url: string;
    actor: string;
    authority: string | undefined;
    filename?: string;
    filenames?: string[]
  }> = [];
  const aborted = new Set<string>();
  const manualVerificationSignals: Array<{ readonly aborted: boolean }> = [];
  const review = (): DocumentBatchReview => ({
    group_id: groupId,
    document_type: "visa",
    batch_id: batches[0],
    status: operation === "discard" ? "processing" : "saved",
    uploaded_count: 0,
    rejected_count: 0,
    matched_count: 0,
    physical_file_count: 0,
    assigned_file_count: 0,
    assigned_passenger_count: 0,
    needs_assignment_count: 0,
    processing_upload_ids: operation === "discard" ? batches.filter(id => !aborted.has(id)) : [],
    saved_at: null,
    created_at: null,
    review_rows: [{
      passenger_id: "synthetic-passenger",
      passenger_name: "Synthetic Traveller",
      passport_number: null,
      departure_city: null,
      document: null,
      documents: []
    }],
    unmatched_documents: [],
    assignment_issues: [],
    rejected_documents: [],
  });
  const adapter: AxiosAdapter = async config => {
    const path = config.url ?? "";
    let data: unknown;
    if (config.method === "get" && path === "/api/v1/document-distribution/groups") {
      data = [{ group_id: groupId, group_name: "Synthetic trip", visa_assigned_count: 0 }];
    } else if (config.method === "get" && path === `/api/v1/document-distribution/groups/${groupId}/visa`) {
      data = review();
    } else if (config.method === "post" && path.endsWith("/abort")) {
      writes.push({
        url: path,
        actor: String(config.headers.get("X-Expected-Actor-Id")),
        authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey
      });
      const id = path.split("/").at(-2)!;
      aborted.add(id);
      data = {
        batch_id: id,
        status: "discarded",
        deleted_document_count: 1,
        deleted_chunk_count: 1,
        deleted_storage_object_count: 1,
        storage_cleanup_pending: false,
        remaining_processing_upload_ids: batches.filter(id => !aborted.has(id))
      };
    } else if (config.method === "post" && path.endsWith("/manual-upload")) {
      const file = (config.data as FormData).get("file") as File;
      writes.push({
        url: path,
        actor: String(config.headers.get("X-Expected-Actor-Id")),
        authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey,
        filename: file.name
      });
      if (operation === "manual-error") {
        throw new AxiosError("Synthetic conflict", undefined, config, undefined, {
          data: { error: { code: "DOC_CONFLICT", message: "Synthetic revision changed" } },
          status: 409,
          statusText: "Conflict",
          headers: {},
          config,
        });
      }
      data = review();
    } else if (config.method === "post" && path.endsWith("/verify")) {
      const files = (config.data as FormData).getAll("files") as File[];
      writes.push({
        url: path,
        actor: String(config.headers.get("X-Expected-Actor-Id")),
        authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey,
        filenames: files.map(file => file.name)
      });
      const accepted = operation !== "manual-review";
      data = {
        group_id: groupId,
        document_type: "visa",
        total_count: files.length,
        accepted_count: accepted ? files.length : 0,
        rejected_count: accepted ? 0 : files.length,
        files: files.map(file => ({
          filename: file.name,
          detected_type: "visa",
          accepted,
          reason: accepted ? "Matched" : "Confirm document type",
          matched_passenger_id: "synthetic-passenger",
          matched_passenger_ids: ["synthetic-passenger"],
          matched_passenger_name: "Synthetic Traveller",
          matched_passenger_names: ["Synthetic Traveller"],
          match_confidence: 1,
          match_status: "matched",
          match_reason: null,
          staging_receipt: accepted ? "synthetic-receipt:" + file.name : null,
          manual_review_token: accepted ? null : "synthetic-manual-type-proof",
        }))
      };
    } else if (config.method === "post" && path.endsWith("/manual-verify")) {
      const form = config.data as FormData;
      const file = form.get("file") as File;
      if (form.get("approval_token") !== "synthetic-manual-type-proof" || !form.get("target_upload_id")) {
        throw new Error("Unexpected synthetic manual proof protocol");
      }
      writes.push({
        url: path,
        actor: String(config.headers.get("X-Expected-Actor-Id")),
        authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey,
        filename: file.name
      });
      if (config.signal) manualVerificationSignals.push(config.signal);
      await manualVerificationGate.promise;
      data = {
        filename: file.name,
        detected_type: "visa",
        accepted: true,
        reason: "Approved",
        matched_passenger_id: "synthetic-passenger",
        matched_passenger_ids: ["synthetic-passenger"],
        matched_passenger_name: "Synthetic Traveller",
        matched_passenger_names: ["Synthetic Traveller"],
        match_confidence: 1,
        match_status: "matched",
        match_reason: null,
        manual_type_approved: true,
        staging_receipt: "synthetic-approved-receipt",
        manual_review_token: null
      };
    } else if (config.method === "post" && path.endsWith("/upload")) {
      const form = config.data as FormData;
      if (form.getAll("files").length || form.getAll("staging_receipts")[0] !== "synthetic-approved-receipt") {
        throw new Error("Unexpected synthetic receipt finalization protocol");
      }
      writes.push({
        url: path,
        actor: String(config.headers.get("X-Expected-Actor-Id")),
        authority: (config as OwnerBoundRequestConfig).expectedAuthorityKey
      });
      data = review();
    } else {
      throw new Error("Unexpected synthetic API request blocked: " + path);
    }
    return { data, status: 200, statusText: "OK", headers: {}, config };
  };
  return { adapter, writes, manualVerificationSignals, releaseManualVerification: () => manualVerificationGate.resolve() };
}
