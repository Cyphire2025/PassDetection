import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { whatsappSourceGroupsApi, type WhatsAppSourceGroupPreview } from "../api/whatsapp-source-groups.api";
import { type WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { useCreateWhatsAppGroup, WHATSAPP_QUERY_KEYS } from "../hooks/use-whatsapp";
import { CreateBroadcastDialog } from "./whatsapp-create-broadcast-dialog";

vi.mock("../api/whatsapp-source-groups.api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/whatsapp-source-groups.api")>();
  return { ...actual, whatsappSourceGroupsApi: { list: vi.fn(), preview: vi.fn(), create: vi.fn() } };
});

const sourceGroups = [
  { id: "source-a", name: "Vietnam trip", submission_count: 4 },
  { id: "source-b", name: "Dubai trip", submission_count: 1 },
];

function preview(id = "source-a", revision = "revision-a"): WhatsAppSourceGroupPreview {
  return {
    source_group_id: id, source_group_name: sourceGroups.find((group) => group.id === id)!.name,
    total_submissions: 4, recipient_count: 1,
    recipients: [{ name: id === "source-a" ? "Aarav Sharma" : "Meera Singh", phone_number: id === "source-a" ? "+919999999991" : "+919999999992", imported_fields: {} }],
    contacts: [
      { source_submission_id: "person-a", name: id === "source-a" ? "Aarav Sharma" : "Meera Singh", phone_number: id === "source-a" ? "+919999999991" : "+919999999992", normalized_phone_number: "+919999999991", issue: null, imported_fields: {} },
      { source_submission_id: "person-b", name: "Other Traveller", phone_number: "+919999999991", normalized_phone_number: "+919999999991", issue: null, imported_fields: {} },
      { source_submission_id: "person-c", name: "Missing Phone", phone_number: "", normalized_phone_number: null, issue: "missing_phone", imported_fields: {} },
      { source_submission_id: "person-d", name: "Unverified Contact", phone_number: "1234", normalized_phone_number: null, issue: "unverified_phone", imported_fields: {} },
    ],
    excluded_count: 2, excluded_counts: { missing_phone: 1, invalid_phone: 0, unverified_phone: 1, missing_name: 0, name_too_long: 0, duplicate_phone: 0 },
    shared_phone_count: 1, needs_attention_count: 2,
    preview_revision: revision,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(whatsappSourceGroupsApi.list).mockResolvedValue(sourceGroups);
  vi.mocked(whatsappSourceGroupsApi.preview).mockImplementation(async (id) => preview(id));
});

function setup(onSubmit = vi.fn().mockResolvedValue(undefined)) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  render(<CreateBroadcastDialog isLoading={false} onClose={vi.fn()} onSubmit={onSubmit} />, { wrapper });
  return { client, onSubmit };
}

async function chooseSource(id = "source-a") {
  fireEvent.click(screen.getByRole("radio", { name: "Create from existing group" }));
  await screen.findByRole("option", { name: "Vietnam trip (4 submissions)" });
  fireEvent.change(screen.getByRole("combobox", { name: "Existing group" }), { target: { value: id } });
}

function addSupport() {
  fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "Travel support" } });
  fireEvent.change(screen.getByRole("textbox", { name: "WhatsApp number" }), { target: { value: "+919999999999" } });
  fireEvent.click(screen.getByRole("button", { name: "Add" }));
}

const saveButton = () => screen.getByRole("button", { name: "Save List" });
const optIn = () => screen.getByRole("checkbox", { name: /I confirm these recipients/ });

describe("create broadcast from an existing group", () => {
  it("keeps every traveller row including shared numbers and contacts needing attention", async () => {
    const { onSubmit } = setup();
    expect(whatsappSourceGroupsApi.list).not.toHaveBeenCalled();
    await chooseSource();
    expect(await screen.findByText("Aarav Sharma")).toBeInTheDocument();
    expect(screen.getAllByText("+919999999991")).toHaveLength(2);
    expect(screen.getByText("WhatsApp number missing")).toBeInTheDocument();
    expect(screen.getByText("Other Traveller")).toBeInTheDocument();
    expect(screen.getAllByText("Shared number · one message")).toHaveLength(2);
    expect(screen.getByRole("textbox", { name: "Group name" })).toHaveValue("Vietnam trip");
    fireEvent.change(screen.getByRole("textbox", { name: "Group name" }), { target: { value: "Vietnam travellers" } });
    addSupport();
    fireEvent.click(optIn());
    fireEvent.click(saveButton());
    await waitFor(() => expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      sourceGroupId: "source-a", name: "Vietnam travellers",
      supportContacts: [{ name: "Travel support", phone_number: "+919999999999" }],
      recipientOptInConfirmed: true, previewRevision: "revision-a",
    }));
  });

  it("requires support contacts and explicit recipient opt-in", async () => {
    const { onSubmit } = setup();
    await chooseSource();
    await screen.findByText("Aarav Sharma");
    fireEvent.click(saveButton());
    expect(await screen.findByText("Add at least one customer support contact.")).toBeInTheDocument();
    addSupport();
    fireEvent.click(saveButton());
    expect(await screen.findByText("Confirm that recipients agreed to receive trip updates on WhatsApp.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("clears previous contacts and opt-in while another group's preview loads", async () => {
    const second = deferred<WhatsAppSourceGroupPreview>();
    vi.mocked(whatsappSourceGroupsApi.preview).mockImplementation((id) => id === "source-a" ? Promise.resolve(preview()) : second.promise);
    setup();
    await chooseSource();
    await screen.findByText("Aarav Sharma");
    fireEvent.click(optIn());
    fireEvent.change(screen.getByRole("combobox", { name: "Existing group" }), { target: { value: "source-b" } });
    expect(screen.queryByText("Aarav Sharma")).not.toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Group name" })).toHaveValue("Dubai trip");
    await act(async () => second.resolve(preview("source-b", "revision-b")));
    await screen.findByText("Meera Singh");
    expect(optIn()).not.toBeChecked();
  });

  it("ignores late responses for a group that is no longer selected", async () => {
    const first = deferred<WhatsAppSourceGroupPreview>();
    vi.mocked(whatsappSourceGroupsApi.preview).mockImplementation((id) => id === "source-a" ? first.promise : Promise.resolve(preview("source-b", "revision-b")));
    setup();
    await chooseSource();
    fireEvent.change(screen.getByRole("combobox", { name: "Existing group" }), { target: { value: "source-b" } });
    await screen.findByText("Meera Singh");
    await act(async () => first.resolve(preview()));
    expect(screen.queryByText("Aarav Sharma")).not.toBeInTheDocument();
    expect(screen.getByText("Meera Singh")).toBeInTheDocument();
  });

  it("keeps an edited broadcast name on refresh and requires opt-in for the refreshed preview", async () => {
    setup();
    await chooseSource();
    await screen.findByText("Aarav Sharma");
    fireEvent.change(screen.getByRole("textbox", { name: "Group name" }), { target: { value: "Custom name" } });
    fireEvent.click(optIn());
    fireEvent.click(screen.getByRole("button", { name: "Refresh preview" }));
    await waitFor(() => expect(whatsappSourceGroupsApi.preview).toHaveBeenCalledTimes(2));
    await screen.findByText("Aarav Sharma");
    expect(screen.getByRole("textbox", { name: "Group name" })).toHaveValue("Custom name");
    expect(optIn()).not.toBeChecked();
  });

  it("refreshes a changed source after a 409 and does not silently retry creation", async () => {
    const onSubmit = vi.fn().mockRejectedValue({ response: { status: 409, data: { detail: "The source group changed. Refresh its preview and confirm the recipients again." } } });
    setup(onSubmit);
    await chooseSource();
    await screen.findByText("Aarav Sharma");
    addSupport();
    fireEvent.click(optIn());
    vi.mocked(whatsappSourceGroupsApi.preview).mockResolvedValue(preview("source-a", "revision-new"));
    fireEvent.click(saveButton());
    expect(await screen.findByText(/This group changed after your preview/)).toBeInTheDocument();
    await waitFor(() => expect(whatsappSourceGroupsApi.preview).toHaveBeenCalledTimes(2));
    await screen.findByText("Aarav Sharma");
    expect(optIn()).not.toBeChecked();
    expect(onSubmit).toHaveBeenCalledTimes(1);
    fireEvent.click(optIn());
    fireEvent.click(saveButton());
    await waitFor(() => expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({ previewRevision: "revision-new" })));
  });

  it("shows other conflict errors without reporting stale contacts or refreshing the preview", async () => {
    const onSubmit = vi.fn().mockRejectedValue({ response: { status: 409, data: { detail: "Wait for queued deliveries to finish." } } });
    setup(onSubmit);
    await chooseSource();
    await screen.findByText("Aarav Sharma");
    addSupport();
    fireEvent.click(optIn());
    fireEvent.click(saveButton());
    expect(await screen.findByText("Wait for queued deliveries to finish.")).toBeInTheDocument();
    expect(whatsappSourceGroupsApi.preview).toHaveBeenCalledTimes(1);
    expect(optIn()).toBeChecked();
  });

  it("shows empty source groups and leaves creation disabled", async () => {
    vi.mocked(whatsappSourceGroupsApi.list).mockResolvedValue([]);
    setup();
    fireEvent.click(screen.getByRole("radio", { name: "Create from existing group" }));
    expect(await screen.findByText(/No active groups available/)).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    expect(whatsappSourceGroupsApi.preview).not.toHaveBeenCalled();
  });

  it("recovers group-list failures with Retry groups", async () => {
    vi.mocked(whatsappSourceGroupsApi.list).mockRejectedValueOnce(new Error("Groups unavailable"));
    setup();
    fireEvent.click(screen.getByRole("radio", { name: "Create from existing group" }));
    expect(await screen.findByText("Groups unavailable")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry groups" }));
    await screen.findByRole("option", { name: "Vietnam trip (4 submissions)" });
    expect(screen.getByRole("combobox", { name: "Existing group" })).toBeEnabled();
  });

  it("blocks zero-contact previews and lets failed previews be retried", async () => {
    vi.mocked(whatsappSourceGroupsApi.preview).mockRejectedValueOnce(new Error("Preview unavailable"));
    setup();
    await chooseSource();
    expect(await screen.findByText("Preview unavailable")).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
    vi.mocked(whatsappSourceGroupsApi.preview).mockResolvedValue({ ...preview(), contacts: [], recipients: [], recipient_count: 0 });
    fireEvent.click(screen.getByRole("button", { name: "Refresh preview" }));
    expect(await screen.findByText(/No traveller rows to import/)).toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("allows saving retained traveller rows even when every number needs attention", async () => {
    const source = preview();
    vi.mocked(whatsappSourceGroupsApi.preview).mockResolvedValue({ ...source, source_import_only: true, contacts: source.contacts!.filter((contact) => contact.issue), recipients: [], recipient_count: 0 });
    const { onSubmit } = setup();
    await chooseSource();
    await screen.findByText("Import only");
    expect(saveButton()).toBeEnabled();
    addSupport();
    fireEvent.click(optIn());
    fireEvent.click(saveButton());
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ sourceGroupId: "source-a" })));
  });

  it("preserves the manual draft when switching methods and resets source selection", async () => {
    setup();
    fireEvent.change(screen.getByRole("textbox", { name: "Group name" }), { target: { value: "Manual list" } });
    await chooseSource();
    await screen.findByText("Aarav Sharma");
    fireEvent.click(screen.getByRole("radio", { name: "Enter contacts or upload Excel" }));
    expect(screen.getByRole("textbox", { name: "Group name" })).toHaveValue("Manual list");
    expect(screen.getByText("Upload Excel contacts")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "Create from existing group" }));
    expect(screen.getByRole("combobox", { name: "Existing group" })).toHaveValue("");
    expect(screen.queryByText("Aarav Sharma")).not.toBeInTheDocument();
    expect(saveButton()).toBeDisabled();
  });

  it("retains the manual creation payload and contact editors", async () => {
    const { onSubmit } = setup();
    fireEvent.change(screen.getByRole("textbox", { name: "Group name" }), { target: { value: "Manual list" } });
    for (const [heading, name, number] of [
      ["Recipients", "Manual traveller", "+919999999991"],
      ["Passport-link support contacts", "Travel support", "+919999999999"],
    ]) {
      const section = within(screen.getByRole("heading", { name: heading }).closest("section")!);
      fireEvent.change(section.getByRole("textbox", { name: "Name" }), { target: { value: name } });
      fireEvent.change(section.getByRole("textbox", { name: "WhatsApp number" }), { target: { value: number } });
      fireEvent.click(section.getByRole("button", { name: "Add" }));
    }
    fireEvent.click(optIn());
    fireEvent.click(saveButton());
    await waitFor(() => expect(onSubmit).toHaveBeenCalledExactlyOnceWith({
      name: "Manual list", contacts: [{ name: "Manual traveller", phone_number: "+919999999991" }],
      rejectedContacts: [], supportContacts: [{ name: "Travel support", phone_number: "+919999999999" }],
      recipientOptInConfirmed: true, importedFieldKeys: [],
    }));
    expect(whatsappSourceGroupsApi.list).not.toHaveBeenCalled();
  });
});

it("invalidates the linked group and broadcast options after source-based creation", async () => {
  const group: WhatsAppBroadcastGroupDetail = {
    id: "broadcast-a", name: "Vietnam trip", recipient_count: 1, total_contact_count: 1,
    recipient_opt_in_confirmed: true, created_at: "2026-09-21T00:00:00Z", updated_at: "2026-09-21T00:00:00Z",
    recipients: [], support_contacts: [], rejected_contact_count: 0,
    linked_client_groups: [{ id: "source-a", name: "Vietnam trip", status: "active" }],
  };
  vi.mocked(whatsappSourceGroupsApi.create).mockResolvedValue(group);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const linksKey = ["upload-links", "source-a", "whatsapp-links"];
  const optionsKey = ["upload-links", "source-a", "whatsapp-broadcast-options"];
  client.setQueryData(linksKey, []);
  client.setQueryData(optionsKey, []);
  const { result } = renderHook(() => useCreateWhatsAppGroup(), { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  await act(async () => {
    await result.current.mutateAsync({ sourceGroupId: "source-a", name: "Vietnam trip", supportContacts: [], recipientOptInConfirmed: true, previewRevision: "revision-a" });
  });
  expect(client.getQueryData(WHATSAPP_QUERY_KEYS.group("broadcast-a"))).toEqual(group);
  expect(client.getQueryState(linksKey)?.isInvalidated).toBe(true);
  expect(client.getQueryState(optionsKey)?.isInvalidated).toBe(true);
});
