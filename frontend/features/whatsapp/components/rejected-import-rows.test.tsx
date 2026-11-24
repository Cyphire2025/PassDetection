import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ExcelRecipientImport, toRejectedContactInputs, type RecipientImportState } from "./whatsapp-recipient-import";

afterEach(cleanup);

it("bounds rejected-row DOM while every original row remains available for review and save", () => {
  const rejectedRows = Array.from({ length: 120 }, (_, index) => ({
    source_file_name: "synthetic.xlsx", sheet_name: "Travellers", row_number: index + 2,
    raw_name: `Synthetic rejected person ${index + 1}`, raw_phone_number: `invalid-${index}`,
    reason_code: "invalid_phone" as const, reason: "Review this number", imported_fields: {},
  }));
  const state: RecipientImportState = { status: "success", fileName: "synthetic.xlsx",
    acceptedCount: 1, addedCount: 1, duplicateCount: 0, rejectedCount: 120, rejectedRows,
    rejectedRowsTruncated: false, omittedRejectedCount: 0, matchingFieldCount: 0, retainedSourceFileCount: 0 };
  render(<ExcelRecipientImport state={state} onFile={vi.fn()} label="Import recipients" />);
  const rows = screen.getByLabelText("Rejected spreadsheet rows");
  expect(within(rows).getAllByRole("article")).toHaveLength(50);
  expect(within(rows).getByText("Synthetic rejected person 1")).toBeInTheDocument();
  const pagination = screen.getByRole("navigation", { name: "Rejected spreadsheet rows pagination" });
  fireEvent.click(within(pagination).getByRole("button", { name: "Next" }));
  expect(within(rows).getAllByRole("article")).toHaveLength(50);
  expect(within(rows).getByText("Synthetic rejected person 51")).toBeInTheDocument();
  fireEvent.click(within(pagination).getByRole("button", { name: "Next" }));
  expect(within(rows).getAllByRole("article")).toHaveLength(20);
  expect(within(rows).getByText("Synthetic rejected person 120")).toBeInTheDocument();
  expect(toRejectedContactInputs(rejectedRows)).toHaveLength(120);
  expect(toRejectedContactInputs(rejectedRows)[119]).toMatchObject({ raw_name: "Synthetic rejected person 120", row_number: 121 });
});
