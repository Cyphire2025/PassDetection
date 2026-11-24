import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TripDetailsDialog, type TripDetailsForm } from "./passport-trip-details-dialog";
import { PassportDocumentImportDialog, PassportDocumentImportProgress } from "./passport-document-import-dialog";
import { TripTimeZoneField } from "./trip-timezone-field";
import { tripDetailsUpdate } from "../utils/passport-group-update";

afterEach(cleanup);
const form: TripDetailsForm = {
  import_only: true, name: " Group ", destination: "", travel_date: "", return_date: "", timezone: " Asia/Kolkata ",
  departure_cities: ["  New  Delhi ", "new delhi", "Mumbai"], base_city_enabled: false, nearest_international_airport_enabled: true,
  staff_code_enabled: false, agent_employee_code_enabled: false, meal_preference_enabled: false, require_selfie: false,
  allow_files_from_device: true, ask_nearest_domestic_airport: false, relation_with_qualifier_enabled: false,
  designation_enabled: false, agency_dealership_name_enabled: false, notes: "",
};
const preview = { group_id: "group-id", total_count: 0, accepted_count: 0, rejected_count: 0, accepted_documents: [], rejected_documents: [] };

it("names and contains the trip dialog, showing a retryable save error and locking Escape during a save", () => {
  const onClose = vi.fn(), onSave = vi.fn();
  const props = { form: { ...form, timezone: "Asia/Kolkata" }, onClose, onSave, onChange: vi.fn(), saveError: "The trip could not be saved. Retry." };
  const view = render(<TripDetailsDialog {...props} isLoading={false} />);
  const dialog = screen.getByRole("dialog", { name: "Edit Trip Details" });
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  expect(screen.getByRole("alert")).toHaveTextContent(props.saveError);
  fireEvent.click(screen.getByRole("button", { name: "Save Details" }));
  expect(onSave).toHaveBeenCalledOnce();
  view.rerender(<TripDetailsDialog {...props} isLoading />);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(onClose).not.toHaveBeenCalled();
  view.rerender(<TripDetailsDialog {...props} isLoading={false} />);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
});

it("keeps accepted-file import steps and prevents dismissing the saving dialog", () => {
  const onClose = vi.fn();
  const props = { preview, files: [], onClose, onSave: vi.fn() };
  const view = render(<PassportDocumentImportDialog {...props} saving={false} />);
  const dialog = screen.getByRole("dialog", { name: "Passport document distribution" });
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  view.rerender(<PassportDocumentImportDialog {...props} saving />);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(onClose).not.toHaveBeenCalled();
  view.rerender(<PassportDocumentImportDialog {...props} saving={false} />);
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(onClose).toHaveBeenCalledOnce();
});

it("reports small upload byte counts accurately with a named progress bar", () => {
  render(<PassportDocumentImportProgress processed={512} total={1024} label="Uploading accepted documents" />);
  expect(screen.getByRole("dialog", { name: "Passport document import" })).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "Uploading accepted documents" })).toHaveAttribute("aria-valuenow", "50");
  expect(screen.getByText("512 B of 1 KB")).toBeInTheDocument();
  expect(screen.queryByText(/files checked/)).not.toBeInTheDocument();
});

it("retains caller descriptions together with only the rendered timezone hint or error", () => {
  const view = render(<TripTimeZoneField id="trip-timezone" aria-describedby="external-help" />);
  expect(screen.getByLabelText("Trip timezone")).toHaveAttribute("aria-describedby", "external-help trip-timezone-hint");
  view.rerender(<TripTimeZoneField id="trip-timezone" aria-describedby="external-help" error="Invalid timezone" />);
  expect(screen.getByLabelText("Trip timezone")).toHaveAttribute("aria-describedby", "external-help trip-timezone-error");
  expect(document.getElementById("trip-timezone-hint")).toBeNull();
});

it("preserves all trip settings while normalizing names, optional dates and city duplicates", () => {
  const result = tripDetailsUpdate("group-id", form, "Fallback");
  expect(result).toMatchObject({ id: "group-id", name: "Group", timezone: "Asia/Kolkata", destination: null,
    travel_date: null, return_date: null, notes: null, departure_cities: ["New Delhi", "Mumbai"], require_selfie: false, allow_files_from_device: true });
  expect(tripDetailsUpdate("group-id", { ...form, name: " ", nearest_international_airport_enabled: false }, "Fallback")).toMatchObject({ name: "Fallback", departure_cities: [] });
});
