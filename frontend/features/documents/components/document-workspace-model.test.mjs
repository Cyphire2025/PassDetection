import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const source = readFileSync(
  new URL("./document-workspace-model.ts", import.meta.url),
  "utf8",
);
const modelModule = await import(
  `data:text/javascript;base64,${Buffer.from(
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
  ).toString("base64")}`
);

const {
  acceptedStagingReceiptsFor,
  countPassengersForDocuments,
  createActiveDocumentSelection,
  createDocumentReviewModel,
  eligibleDeliveryDocumentIds,
  filterDocumentReviewRows,
  updateSelectedDocumentIds,
} = modelModule;

function document(id, deliveryStatus) {
  return { id, delivery_status: deliveryStatus };
}

const review = {
  review_rows: [
    {
      passenger_id: "passenger-1",
      passenger_name: "Asha Rao",
      documents: [document("document-1", "sent"), document("document-2", "queued")],
      document: null,
    },
    {
      passenger_id: "passenger-2",
      passenger_name: "Bilal Khan",
      documents: [],
      document: document("document-3", "delivered"),
    },
    {
      passenger_id: "passenger-3",
      passenger_name: "Chitra Shah",
      documents: [],
      document: null,
    },
  ],
  unmatched_documents: [
    {
      id: "document-unmatched",
      original_filename: "unmatched.pdf",
      match_reason: "Passport number was missing.",
    },
  ],
};

test("the review model preserves multi-document and legacy single-document rows", () => {
  const model = createDocumentReviewModel(review);

  assert.deepEqual(model.counts, {
    all: 3,
    assigned: 2,
    missing: 1,
    sent: 2,
    not_sent: 1,
  });
  assert.deepEqual(model.assignedDocumentIds, [
    "document-1",
    "document-2",
    "document-3",
  ]);
  assert.deepEqual(
    model.documentsByPassengerId.get("passenger-2").map(({ id }) => id),
    ["document-3"],
  );
  assert.equal(model.assignmentIssues[0].reason, "Passport number was missing.");
});

test("search and delivery filters retain the previous passenger-level semantics", () => {
  const model = createDocumentReviewModel(review);

  assert.deepEqual(
    filterDocumentReviewRows(model, "all", "  bilal ").map((row) => row.passenger_id),
    ["passenger-2"],
  );
  assert.deepEqual(
    filterDocumentReviewRows(model, "sent", "").map((row) => row.passenger_id),
    ["passenger-1", "passenger-2"],
  );
  assert.deepEqual(
    filterDocumentReviewRows(model, "not_sent", "").map((row) => row.passenger_id),
    ["passenger-1"],
  );
  assert.deepEqual(
    filterDocumentReviewRows(model, "missing", "").map((row) => row.passenger_id),
    ["passenger-3"],
  );
});

test("selection helpers discard stale ids and keep assigned and unmatched actions separate", () => {
  const model = createDocumentReviewModel(review);
  const selection = createActiveDocumentSelection(
    ["stale", "document-2", "document-unmatched"],
    model,
  );

  assert.deepEqual(selection.documentIds, ["document-2", "document-unmatched"]);
  assert.deepEqual(selection.assignedDocumentIds, ["document-2"]);
  assert.deepEqual(selection.unmatchedDocumentIds, ["document-unmatched"]);
  assert.equal(countPassengersForDocuments(model, selection.assignedDocumentIdSet), 1);
  assert.deepEqual(
    updateSelectedDocumentIds(["keep", "replace"], ["replace", "new"], true),
    ["keep", "replace", "new"],
  );
  assert.deepEqual(
    updateSelectedDocumentIds(["keep", "remove"], ["remove"], false),
    ["keep"],
  );
});

test("upload receipts and delivery defaults retain their exact API payload inputs", () => {
  assert.deepEqual(
    acceptedStagingReceiptsFor({
      files: [
        { accepted: true, staging_receipt: "receipt-1" },
        { accepted: false, staging_receipt: "receipt-2" },
        { accepted: true, staging_receipt: null },
      ],
    }),
    ["receipt-1", null],
  );
  assert.deepEqual(
    eligibleDeliveryDocumentIds({
      recipients: [
        { eligible: true, document_id: "document-1" },
        { eligible: false, document_id: "document-2" },
        { eligible: true, document_id: null },
      ],
    }),
    ["document-1"],
  );
});
