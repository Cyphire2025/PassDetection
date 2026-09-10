import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clientDetailsApi, type ClientDetailsEditorResponse } from "../api/client-details.api";
import type { PassportSubmission } from "@/types/passport.types";
import { ClientDetailsEditDialog } from "./client-details-edit-dialog";
import { ClientProvidedFieldsCard } from "./client-provided-fields-card";

vi.mock("../api/client-details.api", () => ({ clientDetailsApi: { get: vi.fn(), update: vi.fn() } }));

const descriptor = (): ClientDetailsEditorResponse => ({
  updated_at: "2026-09-11T02:00:00Z",
  fields: [
    { key: "agent_employee_code", label: "Producer Code", value: "AIG12345", required: true, type: "text", options: [], max_length: 100 },
    { key: "agency_dealership_name", label: "Producer Name", value: "Example Producer", required: false, type: "text", options: [], max_length: 255 },
    { key: "client_email", label: "Email entered by client", value: "test@example.test", required: true, type: "email", options: [], max_length: 255 },
  ],
  custom_answers: [{ question_id: "question-1", label: "Transport", value: "Legacy route", options: ["Bus", "Car"], required: true, max_length: 120 }],
  custom_detail_answers: [{ detail_id: "detail-1", label: "Internal reference", value: "ABC-10", required: false, max_length: 500 }],
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(clientDetailsApi.get).mockResolvedValue(descriptor());
  vi.mocked(clientDetailsApi.update).mockResolvedValue({ id: "submission-1", group_id: "group-1", status: "staff_approved" } as PassportSubmission);
});

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onClose = vi.fn();
  render(<QueryClientProvider client={client}><ClientDetailsEditDialog id="submission-1" groupId="group-1" onClose={onClose} /></QueryClientProvider>);
  return { client, onClose };
}

describe("staff client-details correction", () => {
  it("loads saved labels and sends only the explicitly corrected code with a version check", async () => {
    const { onClose, client } = setup();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const code = await screen.findByLabelText("Producer Code");
    expect(code).toHaveValue("AIG12345");
    expect(screen.getByText(/Queued private document or QR deliveries/)).toHaveTextContent("will need a fresh preview after a correction. Regular reminders are unchanged.");
    expect(screen.getByLabelText("Transport")).toHaveValue("Legacy route");
    expect(screen.getByRole("button", { name: "Save corrections" })).toBeDisabled();
    await userEvent.clear(code);
    await userEvent.type(code, "12345");
    await userEvent.click(screen.getByRole("button", { name: "Save corrections" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledOnce());
    expect(clientDetailsApi.update).toHaveBeenCalledExactlyOnceWith("submission-1", { expected_updated_at: descriptor().updated_at, agent_employee_code: "12345" });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["whatsapp"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["upload-links", "group-1"] });
  });

  it("preserves custom IDs and never submits labels, options, or untouched answers", async () => {
    setup();
    await screen.findByLabelText("Producer Code");
    await userEvent.selectOptions(screen.getByLabelText("Transport"), "Bus");
    await userEvent.clear(screen.getByLabelText("Internal reference"));
    await userEvent.click(screen.getByRole("button", { name: "Save corrections" }));
    await waitFor(() => expect(clientDetailsApi.update).toHaveBeenCalledOnce());
    expect(clientDetailsApi.update).toHaveBeenCalledWith("submission-1", {
      expected_updated_at: descriptor().updated_at,
      custom_answers: [{ question_id: "question-1", value: "Bus" }],
      custom_detail_answers: [{ detail_id: "detail-1", value: "" }],
    });
  });

  it("allows correcting retained retired answers without changing their labels or identifiers", async () => {
    const data = descriptor();
    data.custom_answers[0].options = [];
    data.custom_answers[0].required = false;
    vi.mocked(clientDetailsApi.get).mockResolvedValue(data);
    setup();
    const answer = await screen.findByRole("textbox", { name: "Transport" });
    await userEvent.clear(answer);
    await userEvent.type(answer, "Corrected old route");
    await userEvent.click(screen.getByRole("button", { name: "Save corrections" }));
    await waitFor(() => expect(clientDetailsApi.update).toHaveBeenCalledOnce());
    expect(clientDetailsApi.update).toHaveBeenCalledWith("submission-1", {
      expected_updated_at: data.updated_at,
      custom_answers: [{ question_id: "question-1", value: "Corrected old route" }],
    });
  });

  it("cancels without saving and does not automatically remove code prefixes", async () => {
    const { onClose } = setup();
    const code = await screen.findByLabelText("Producer Code");
    await userEvent.clear(code);
    await userEvent.type(code, "MANUAL-12345");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(clientDetailsApi.update).not.toHaveBeenCalled();
  });

  it("keeps conflicting edits visible and requires an explicit latest-version reload", async () => {
    vi.mocked(clientDetailsApi.update).mockRejectedValueOnce({ status: 409, code: "HTTP_409" });
    setup();
    const code = await screen.findByLabelText("Producer Code");
    await userEvent.clear(code);
    await userEvent.type(code, "12345");
    await userEvent.click(screen.getByRole("button", { name: "Save corrections" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Your edits have not been applied");
    expect(screen.getByRole("textbox", { name: "Producer Code" })).toHaveValue("12345");
    expect(screen.getByRole("textbox", { name: "Producer Code" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save corrections" })).toBeDisabled();
    const latest = descriptor();
    latest.updated_at = "2026-09-11T02:05:00Z";
    latest.fields[0].value = "AIG54321";
    vi.mocked(clientDetailsApi.get).mockResolvedValue(latest);
    await userEvent.click(screen.getByRole("button", { name: "Reload latest details" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Producer Code" })).toHaveValue("AIG54321"));
    await userEvent.clear(screen.getByRole("textbox", { name: "Producer Code" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Producer Code" }), "54321");
    await userEvent.click(screen.getByRole("button", { name: "Save corrections" }));
    await waitFor(() => expect(clientDetailsApi.update).toHaveBeenCalledTimes(2));
    expect(clientDetailsApi.update).toHaveBeenLastCalledWith("submission-1", { expected_updated_at: latest.updated_at, agent_employee_code: "54321" });
  });

  it("blocks blank required corrections even when submission bypasses native validation", async () => {
    setup();
    await userEvent.clear(await screen.findByLabelText("Producer Code"));
    fireEvent.submit(screen.getByRole("button", { name: "Save corrections" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("Producer Code is required");
    expect(clientDetailsApi.update).not.toHaveBeenCalled();
  });

  it("does not force unrelated legacy values to change when only a producer code is corrected", async () => {
    const data = descriptor();
    data.fields[2].value = "legacy-import-without-email";
    vi.mocked(clientDetailsApi.get).mockResolvedValue(data);
    setup();
    await userEvent.clear(await screen.findByRole("textbox", { name: "Producer Code" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Producer Code" }), "12345");
    await userEvent.click(screen.getByRole("button", { name: "Save corrections" }));
    await waitFor(() => expect(clientDetailsApi.update).toHaveBeenCalledOnce());
    expect(clientDetailsApi.update).toHaveBeenCalledWith("submission-1", { expected_updated_at: data.updated_at, agent_employee_code: "12345" });
  });

  it("does not duplicate a pending save or permit closing during it", async () => {
    let finish!: (value: PassportSubmission) => void;
    vi.mocked(clientDetailsApi.update).mockReturnValueOnce(new Promise((resolve) => { finish = resolve; }));
    const { onClose } = setup();
    const code = await screen.findByLabelText("Producer Code");
    await userEvent.type(code, "X");
    const form = screen.getByRole("button", { name: "Save corrections" }).closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    await waitFor(() => expect(clientDetailsApi.update).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close details editor" })).toBeDisabled();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    await act(async () => finish({ id: "submission-1", group_id: "group-1" } as PassportSubmission));
  });

  it("keeps the draft and original version when a background query invalidation loads a newer record", async () => {
    const { client } = setup();
    const code = await screen.findByRole("textbox", { name: "Producer Code" });
    await userEvent.clear(code);
    await userEvent.type(code, "12345");
    const newer = descriptor();
    newer.updated_at = "2026-09-11T02:30:00Z";
    newer.fields[0].value = "OTHER-54321";
    vi.mocked(clientDetailsApi.get).mockResolvedValue(newer);
    await act(async () => {
      await client.invalidateQueries({ queryKey: ["passports"] });
      await client.invalidateQueries({ queryKey: ["passport-client-details-editor", "submission-1"] });
    });
    expect(screen.getByRole("textbox", { name: "Producer Code" })).toHaveValue("12345");
    await userEvent.click(screen.getByRole("button", { name: "Save corrections" }));
    await waitFor(() => expect(clientDetailsApi.update).toHaveBeenCalledOnce());
    expect(clientDetailsApi.update).toHaveBeenCalledWith("submission-1", {
      expected_updated_at: descriptor().updated_at, agent_employee_code: "12345",
    });
  });

  it("retains the draft after a failed request without retrying the mutation automatically", async () => {
    vi.mocked(clientDetailsApi.update).mockRejectedValueOnce({ status: 503, message: "Temporarily unavailable" });
    setup();
    await userEvent.type(await screen.findByLabelText("Producer Code"), "X");
    await userEvent.click(screen.getByRole("button", { name: "Save corrections" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Temporarily unavailable");
    expect(screen.getByRole("textbox", { name: "Producer Code" })).toHaveValue("AIG12345X");
    expect(clientDetailsApi.update).toHaveBeenCalledOnce();
  });

  it("includes saved custom details in the card while hiding edits from read-only staff", () => {
    render(<ClientProvidedFieldsCard passport={{
      id: "submission-1", group_id: "group-1", status: "staff_approved", confirmed_fields: { agent_employee_code: "AIG12345" },
      staff_metadata: { agent_employee_code_label: "Producer Code" },
      custom_answers: [{ question_id: "q", label: "Same label", value: "Bus" }],
      custom_detail_answers: [{ detail_id: "d", label: "Same label", value: "Reference-1" }],
    } as unknown as PassportSubmission} />);
    expect(screen.getByText("AIG12345")).toBeInTheDocument();
    expect(screen.getByText("Reference-1")).toBeInTheDocument();
    expect(screen.getAllByText("Same label")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Edit client-provided group details" })).not.toBeInTheDocument();
  });

  it("does not revive a cleared value from older staff metadata or OCR", () => {
    render(<ClientProvidedFieldsCard canEdit passport={{
      id: "submission-1", group_id: "group-1", status: "staff_approved",
      confirmed_fields: { agency_dealership_name: null },
      staff_metadata: { agency_dealership_name: "Stale producer", agency_dealership_name_label: "Producer Name" },
      extracted_fields: { agency_dealership_name: "Old OCR producer" },
    } as unknown as PassportSubmission} />);
    expect(screen.queryByText("Stale producer")).not.toBeInTheDocument();
    expect(screen.queryByText("Old OCR producer")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit client-provided group details" })).toBeInTheDocument();
  });

  it("uses the same per-key confirmed, extracted, then staff precedence as matching", () => {
    render(<ClientProvidedFieldsCard passport={{
      id: "submission-1", group_id: "group-1", status: "staff_approved",
      confirmed_fields: { agency_dealership_name: "Confirmed producer" },
      extracted_fields: { agency_dealership_name: "OCR producer", agent_employee_code: "EXTRACTED-123" },
      staff_metadata: { agency_dealership_name: "Staff producer", agent_employee_code: "STAFF-123" },
    } as unknown as PassportSubmission} />);
    expect(screen.getByText("Confirmed producer")).toBeInTheDocument();
    expect(screen.getByText("EXTRACTED-123")).toBeInTheDocument();
    expect(screen.queryByText("STAFF-123")).not.toBeInTheDocument();
    expect(screen.queryByText("OCR producer")).not.toBeInTheDocument();
  });
});
