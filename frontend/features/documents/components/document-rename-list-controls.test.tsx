import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fireEvent, render, screen } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import type { RenameDocumentBatch, RenameDocumentBatchSummary } from "@/types/document-rename.types";
import { SavedRenameBatches } from "./saved-rename-batches";
import { RenameResults } from "./rename-results";

const batches = (count = 2): RenameDocumentBatchSummary[] => Array.from({ length: count }, (_, index) => ({
  batch_id: `batch-${index}`, title: `Synthetic batch ${index}`, status: "completed", total_count: 1,
  visa_count: 1, ticket_count: 0, unknown_count: 0, created_at: "2026-10-01",
  zip_download_url: `http://127.0.0.1:47852/synthetic-${index}.zip`,
}));
const props = () => ({ batches: batches(), selectedBatchIds: [] as string[], isLoading: false,
  isOpening: false, isDeleting: false, onSelectionChange: vi.fn(), onOpen: vi.fn(), onDelete: vi.fn() });
function fixture(name: string, value: string) {
  const directory = process.env.RENAME_CONTROLS_FIXTURE_DIR;
  if (directory) { mkdirSync(directory, { recursive: true }); writeFileSync(join(directory, name), value); }
}

it("bounds native membership reads while rendering a fully selected512batch list", () => {
  const count = 512;
  let indexedReads = 0;
  const observe = <T,>(values: T[]) => new Proxy(values, { get(target, key, receiver) {
    if (typeof key === "string" && /^\d+$/.test(key)) indexedReads++;
    return Reflect.get(target, key, receiver);
  } });
  const rows = batches(count);
  // Preserve actual native map/filter/includes/iteration. Observe only the two
  // intermediate ID arrays where repeated scans can create quadratic work.
  const observedRows = new Proxy(rows, { get(target, key, receiver) {
    if (key === "map") return (callback: Parameters<typeof rows.map>[0]) => {
      const mapped = target.map(callback);
      return typeof mapped[0] === "string" ? observe(mapped) : mapped;
    };
    return Reflect.get(target, key, receiver);
  } });
  const selected = new Proxy(rows.map(row => row.batch_id), { get(target, key, receiver) {
    if (key === "filter") return (callback: Parameters<typeof target.filter>[0]) => observe(target.filter(callback));
    return Reflect.get(target, key, receiver);
  } });
  render(<SavedRenameBatches {...props()} batches={observedRows} selectedBatchIds={selected} />);
  expect(screen.getAllByRole("checkbox").filter(box => (box as HTMLInputElement).checked)).toHaveLength(count + 1);
  fixture("membership.json", JSON.stringify({ rows: count, indexedMembershipArrayReads: indexedReads }) + "\n");
  expect(indexedReads, `Actual intermediate ID-array reads: ${indexedReads}`).toBeLessThanOrEqual(count * 8);
});

it("preserves selected ordering and duplicates while excluding stale IDs from every action", () => {
  const actions = props();
  render(<SavedRenameBatches {...actions} selectedBatchIds={["hidden", "batch-1", "batch-1", "batch-0"]} />);
  expect(screen.getByRole("checkbox", { name: "Select all" })).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Delete Selected (3)" }));
  expect(actions.onDelete).toHaveBeenCalledExactlyOnceWith(["batch-1", "batch-1", "batch-0"]);
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Synthetic batch 1" }));
  expect(actions.onSelectionChange).toHaveBeenLastCalledWith(["batch-0"]);
  fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
  expect(actions.onSelectionChange).toHaveBeenLastCalledWith(["batch-0", "batch-1"]);
  fireEvent.click(screen.getAllByRole("button", { name: "Open" })[0]);
  expect(actions.onOpen).toHaveBeenCalledExactlyOnceWith("batch-0");
});

it("keeps download destinations and link semantics with one interactive element per action", () => {
  const saved = <SavedRenameBatches {...props()} batches={batches(1)} />;
  const batch: RenameDocumentBatch = { ...batches(1)[0], items: [{
    id: "item", original_filename: "synthetic.pdf", renamed_filename: "Renamed.pdf", detected_type: "visa",
    extracted_name: null, extracted_passport_number: null, extracted_reference: null, status: "renamed", reason: null,
    download_url: "http://127.0.0.1:47852/synthetic.pdf",
  }] };
  const results = <RenameResults batch={batch} onBack={vi.fn()} />;
  fixture("controls.html", renderToStaticMarkup(<><section aria-label="Saved fixture">{saved}</section><section aria-label="Results fixture">{results}</section></>));
  render(<>{saved}{results}</>);
  const zip = screen.getByRole("link", { name: "ZIP" });
  const resultZip = screen.getByRole("link", { name: "Download ZIP" });
  for (const link of [zip, resultZip]) {
    expect(link).toHaveAttribute("href", batch.zip_download_url);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link.querySelector("button, input, select, textarea, a")).toBeNull();
  }
  const file = screen.getByRole("link", { name: "File" });
  expect(file).toHaveAttribute("href", batch.items[0].download_url);
  expect(file.querySelector("button")).toBeNull();
});

it("preserves pending deletion guards without starting competing selection or delete actions", () => {
  const actions = props();
  render(<SavedRenameBatches {...actions} selectedBatchIds={["batch-0"]} isDeleting />);
  for (const checkbox of screen.getAllByRole("checkbox")) expect(checkbox).toBeDisabled();
  for (const button of screen.getAllByRole("button", { name: /Delete/ })) {
    expect(button).toBeDisabled(); fireEvent.click(button);
  }
  expect(actions.onDelete).not.toHaveBeenCalled();
  expect(actions.onSelectionChange).not.toHaveBeenCalled();
});
