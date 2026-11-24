import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentVerificationResult, VerifiedDistributedDocument } from "@/types/document-distribution.types";
import type { DocumentFilenameReplacement } from "../services/document-upload-batching";
import { documentDistributionApi } from "./document-distribution.api";

const http = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: http }));
vi.mock("@/lib/api/streamed-download", () => ({ downloadStreamedResponse: vi.fn() }));

function verified(name: string, accepted: boolean): VerifiedDistributedDocument {
  return {
    filename: name,
    detected_type: "visa",
    accepted,
    reason: accepted ? "Matched" : "Review type",
    matched_passenger_id: accepted ? "synthetic-passenger" : null,
    matched_passenger_name: accepted ? "Synthetic Traveller" : null,
    matched_passenger_ids: accepted ? ["synthetic-passenger"] : [],
    matched_passenger_names: accepted ? ["Synthetic Traveller"] : [],
    match_confidence: accepted ? 1 : 0,
    match_status: accepted ? "matched" : "needs_review",
    match_reason: null,
    staging_receipt: accepted ? "synthetic-receipt:" + name : null,
    manual_review_token: accepted ? null : "synthetic-approval:" + name,
  };
}

function respond(accept: (file: File) => boolean) {
  http.post.mockImplementation(async (_url: string, body: FormData, config: { signal?: AbortSignal }) => {
    const files = (body.getAll("files") as File[]).map(file => verified(file.name, accept(file)));
    expect(body.get("upload_id")).toBeTruthy();
    expect(body.get("chunk_id")).toBeTruthy();
    expect(config.signal?.aborted).not.toBe(true);
    return {
      data: {
        group_id: "synthetic-group",
        document_type: "visa",
        total_count: files.length,
        accepted_count: files.filter(file => file.accepted).length,
        rejected_count: files.filter(file => !file.accepted).length,
        files,
      } satisfies DocumentVerificationResult
    };
  });
}

const pdf = (name: string) => new File(["%PDF synthetic"], name, { type: "application/pdf" });

beforeEach(() => {
  vi.resetAllMocks();
  let id = 0;
  vi.spyOn(crypto, "randomUUID").mockImplementation(() => `00000000-0000-4000-8000-${String(++id).padStart(12, "0")}`);
});
afterEach(() => vi.restoreAllMocks());

it("retains the complete ordered public distribution facade", () => {
  expect(Object.keys(documentDistributionApi)).toEqual([
    "listGroups", "getReview", "exportReview", "verifyDocuments", "manuallyVerifyDocument",
    "uploadDocuments", "abortUpload", "reuploadPassengerDocument", "manualUploadPassengerDocument",
    "deleteDocuments", "unassignDocuments", "saveBatch", "previewWhatsAppDelivery", "sendWhatsAppDelivery",
    "getDeliveryTracking",
  ]);
});

it.each(["no-passenger", "unconfirmed-match"])("does not stage an accepted flag without a valid passenger match: %s", async kind => {
  const file = verified("unmatched.pdf", true);
  if (kind === "no-passenger") {
    file.matched_passenger_id = null;
    file.matched_passenger_ids = [];
  } else {
    file.match_status = "needs_review";
  }
  http.post.mockResolvedValue({ data: {
    group_id: "synthetic-group", document_type: "visa", total_count: 1,
    accepted_count: 1, rejected_count: 0, files: [file],
  } });
  const plan = await documentDistributionApi.verifyDocuments("synthetic-group", "visa", [pdf("unmatched.pdf")]);
  expect(plan.stagingManifest.totalFiles).toBe(0);
  expect(plan.stagingManifest.chunks).toEqual([]);
  expect(plan.verification).toMatchObject({ accepted_count: 0, rejected_count: 1 });
  expect(plan.verification.files[0]).toMatchObject({ accepted: false, staging_receipt: null });
});

describe(
  "actual document verification transport and output",
  () => {
    it(
      "bounds filename lookup work across512files while retaining verification, receipt and candidate output",
      async () => {
        const names = Array.from({ length: 512 }, (_, index) => `synthetic-${index}.pdf`);
        let reads = 0;
        const replacements = names.toReversed().map((name, index) => ({
          get filename() {
            reads += 1;
            return name;
          },
          documents: [{ id: "synthetic-replacement-" + index, updated_at: "2026-10-01T00:00:00Z" }],
        }));
        respond(file => Number(file.name.slice(10, -4)) % 2 === 0);
        const progress = vi.fn();
        const plan = await documentDistributionApi.verifyDocuments("synthetic-group", "visa", names.map(pdf), progress, undefined, replacements);
        const measuredReads = reads;
        console.info("synthetic filename workload", { files: names.length, replacements: replacements.length, propertyReads: measuredReads });
        expect(http.post).toHaveBeenCalledTimes(32);
        expect(plan.verification.accepted_count).toBe(256);
        expect(plan.verification.rejected_count).toBe(256);
        expect(plan.verification.files.map(file => file.filename)).toEqual(names);
        expect(plan.stagingManifest.totalFiles).toBe(256);
        expect(plan.stagingManifest.chunks.flatMap(chunk => chunk.receipts)).toEqual(names.filter((_, i) => i % 2 === 0).map(name => "synthetic-receipt:" + name));
        expect(plan.manualReviewCandidates?.map(candidate => candidate.fileIndex)).toEqual(names.map((_, i) => i).filter(i => i % 2));
        for (const candidate of plan.manualReviewCandidates ?? []) {
          expect(candidate.filenameReplacement).toBe(replacements.find(entry => entry.filename === candidate.file.name));
        }
        expect(progress.mock.calls.at(-1)?.[0]).toMatchObject({ percent: 100, completedFiles: 512 });
        // Count the actual replacement-filename property reads; no wall-clock or
        // test-only copy of the production search algorithm is used for this bound.
        expect(measuredReads).toBeLessThanOrEqual(4096);
      }
    );

    it(
      "keeps exact names, first-match candidate identity and every duplicate replacement in original order",
      async () => {
        const names = ["same.pdf", ...Array.from({ length: 15 }, (_, i) => `other-${i}.pdf`), "same.pdf", "__proto__.pdf", "A.pdf", "a.pdf", "旅券 ?#%.pdf"];
        const replacements: DocumentFilenameReplacement[] = [
          { filename: "same.pdf", documents: [{ id: "first", updated_at: "first-time" }] },
          { filename: "旅券 ?#%.pdf", documents: [] },
          { filename: "same.pdf", documents: [{ id: "duplicate", updated_at: "second-time" }] },
          { filename: "A.pdf", documents: [] },
          { filename: "a.pdf", documents: [] },
          { filename: "__proto__.pdf", documents: [] },
        ];
        let index = 0;
        respond(() => index++ !== 0);
        const plan = await documentDistributionApi.verifyDocuments("synthetic-group", "visa", names.map(pdf), undefined, undefined, replacements);
        expect(plan.manualReviewCandidates?.[0].filenameReplacement).toBe(replacements[0]);
        expect(plan.stagingManifest.chunks[0].filenameReplacements).toEqual([]);
        expect(plan.stagingManifest.chunks[1].filenameReplacements).toEqual(replacements);
        expect(plan.verification.files.map(file => file.filename)).toEqual(names);
        expect(plan.verification.files.every(file => file.staging_receipt === null && file.manual_review_token === null)).toBe(true);
        expect(plan.manualReviewCandidates?.[0].approvalToken).toBe("synthetic-approval:same.pdf");
      }
    );

    it(
      "rejects a response count mismatch instead of manufacturing staging ownership",
      async () => {
        http.post.mockResolvedValue({ data: { files: [] } });
        await expect(documentDistributionApi.verifyDocuments("synthetic-group", "visa", [pdf("one.pdf")]))
          .rejects.toThrow("did not match the selected PDFs");
        expect(http.post).toHaveBeenCalledTimes(1);
      }
    );
  }
);
