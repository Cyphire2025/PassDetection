import { act, fireEvent, render as renderUi, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CreateUploadLinkModal } from "./create-upload-link-modal";

function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { gcTime: Infinity } } });
  return renderUi(ui, { wrapper: ({ children }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });
}

const { createLink, broadcastId, workspace, account, clipboard } = vi.hoisted(() => ({
  createLink: vi.fn(),
  clipboard: vi.fn(),
  workspace: { agencyId: "agency-1" as string | null, data: { agency_id: "agency-1" } as { agency_id: string } | undefined, sessionKey: "session-1", isError: false, refetch: vi.fn() },
  account: { id: "initial-actor", role: "agency_staff", agency_id: "agency-1" },
  broadcastId: "ab75ac17-ad58-4629-a28b-3e02bef9ca31",
}));

vi.mock("@/lib/utils/clipboard", () => ({ copyTextToClipboard: clipboard }));

vi.mock("../hooks/use-upload-links", () => ({
  useCreateUploadLink: () => ({ mutateAsync: createLink, isPending: false }),
}));
vi.mock("@/stores/auth.store", () => ({
  selectUserRole: (state: { role: string }) => state.role,
  selectUser: (state: { user: unknown }) => state.user,
  useAuthStore: Object.assign((selector: (state: unknown) => unknown) => selector({ role: account.role, user: account }), {
    getState: () => ({ user: account }),
  }),
}));
vi.mock("@/features/companies/hooks/use-company-workspace", () => ({ useCompanyWorkspace: () => workspace }));
vi.mock("@/features/companies/components/company-picker", () => ({
  CompanyPicker: ({ onChange, error }: { onChange: (company: { id: string; name: string; status: string }) => void; error?: string }) => <><button type="button" onClick={() => onChange({ id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "Example company", status: "active" })}>Select company</button>{error && <p role="alert">{error}</p>}</>,
}));
vi.mock("./whatsapp-broadcast-selector", () => ({
  WhatsAppBroadcastSelector: ({ onChange, onMatchingFieldsChange }: {
    onChange: (ids: string[]) => void;
    onMatchingFieldsChange: (fields: Record<string, string[]>) => void;
  }) => <button type="button" onClick={() => {
    onChange([broadcastId]);
    onMatchingFieldsChange({ [broadcastId]: ["phone"] });
  }}>Select WhatsApp broadcast</button>,
}));
vi.mock("@/lib/utils/public-url", () => ({
  getPassportUploadTargets: () => [{ key: "web", label: "Client", description: "Upload documents", url: "https://example.test/upload/test-token" }],
}));

beforeEach(() => {
  Object.assign(workspace, { agencyId: "agency-1", data: { agency_id: "agency-1" }, sessionKey: "session-1", isError: false });
  workspace.refetch.mockReset();
  account.role = "agency_staff";
  account.id = "initial-actor";
  createLink.mockReset().mockResolvedValue({ id: "created-group", token: "test-token" });
  clipboard.mockReset().mockResolvedValue(undefined);
});
afterEach(() => vi.useRealTimers());

function fillGroupDetails() {
  fireEvent.click(screen.getByRole("button", { name: "Select company" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Group Name" }), { target: { value: "Autumn Group" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Destination" }), { target: { value: "Dubai" } });
  fireEvent.change(screen.getByLabelText(/Travel\/Departure Date/), { target: { value: "2026-10-01" } });
  fireEvent.change(screen.getByLabelText(/Return Date/), { target: { value: "2026-10-08" } });
}

describe("create upload link", () => {
  it("does not publish an abandoned copy failure into a reset group draft", async () => {
    let fail!: (reason: Error) => void;
    clipboard.mockReturnValueOnce(new Promise<void>((_, reject) => { fail = reject; }));
    const onClose = vi.fn();
    render(<CreateUploadLinkModal isOpen onClose={onClose} />);
    fillGroupDetails();
    fireEvent.click(screen.getByRole("button", { name: "Generate Links" }));
    await screen.findByRole("heading", { name: "Links Generated" });
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalledOnce();
    await act(async () => fail(new Error("Old clipboard permission denied")));
    expect(screen.getByRole("textbox", { name: "Group Name" })).toHaveValue("");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not create a confirmation timer after a pending copy's form unmounts", async () => {
    let finish!: () => void;
    clipboard.mockReturnValueOnce(new Promise<void>((resolve) => { finish = resolve; }));
    const { unmount } = render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    fireEvent.click(screen.getByRole("button", { name: "Generate Links" }));
    await screen.findByRole("heading", { name: "Links Generated" });
    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    unmount();
    const timersAfterUnmount = vi.getTimerCount();
    await act(async () => finish());
    expect(vi.getTimerCount()).toBe(timersAfterUnmount);
  });

  it("does not publish an old group link if creation finishes after the signed-in actor changes", async () => {
    let finish!: (result: { id: string; token: string }) => void;
    createLink.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    fireEvent.click(screen.getByRole("button", { name: "Generate Links" }));
    await waitFor(() => expect(createLink).toHaveBeenCalledOnce());
    account.id = "replacement-actor";
    await act(async () => { finish({ id: "old-group", token: "old-private-token" }); });
    expect(screen.queryByRole("textbox", { name: "Client upload link" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Group Name" })).toHaveValue("Autumn Group");
  });
  it("waits for workspace resolution before accepting form input and enables direct superadmin company selection", async () => {
    workspace.agencyId = null;
    workspace.data = undefined;
    account.role = "super_admin";
    const view = render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    expect(screen.getByRole("status", { name: "Loading company information" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Group Name")).not.toBeInTheDocument();
    workspace.agencyId = "resolved-agency";
    workspace.data = { agency_id: "resolved-agency" };
    view.rerender(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    expect(screen.queryByLabelText(/agency workspace/i)).not.toBeInTheDocument();
    fillGroupDetails();
    fireEvent.click(screen.getByRole("button", { name: "Generate Links" }));
    await waitFor(() => expect(createLink).toHaveBeenCalledWith(expect.objectContaining({ agency_id: "resolved-agency", company_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" })));
  });

  it("discards the selected company and group draft on session changes", () => {
    const view = render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    workspace.sessionKey = "session-2";
    view.rerender(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    expect(screen.getByLabelText("Group Name")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Generate Links" }));
    expect(createLink).not.toHaveBeenCalled();
  });

  it("keeps the same workspace draft through a failed revalidation and retry while hiding its controls", async () => {
    const view = render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    workspace.agencyId = null;
    workspace.isError = true;
    view.rerender(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("workspace is unavailable");
    expect(screen.queryByLabelText("Group Name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate Links" })).not.toBeInTheDocument();
    expect(createLink).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(workspace.refetch).toHaveBeenCalledOnce();
    workspace.agencyId = "agency-1";
    workspace.isError = false;
    view.rerender(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    expect(screen.getByLabelText("Group Name")).toHaveValue("Autumn Group");
    fireEvent.click(screen.getByRole("button", { name: "Generate Links" }));
    await waitFor(() => expect(createLink).toHaveBeenCalledWith(expect.objectContaining({ company_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "Autumn Group", destination: "Dubai" })));
  });

  it("discards the old draft if revalidation resolves a different workspace in the same session", () => {
    const view = render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    workspace.agencyId = "new-agency";
    workspace.data = { agency_id: "new-agency" };
    view.rerender(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    expect(screen.getByLabelText("Group Name")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Generate Links" }));
    expect(createLink).not.toHaveBeenCalled();
  });

  it("creates an import group using only group details and provides its Excel workspace link", async () => {
    const user = userEvent.setup();
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    await user.click(screen.getByRole("radio", { name: /^Import data/ }));
    expect(screen.queryByRole("switch", { name: /Passport/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select WhatsApp broadcast" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create Group" }));

    await waitFor(() => expect(createLink).toHaveBeenCalledTimes(1));
    expect(createLink).toHaveBeenCalledWith(expect.objectContaining({
      import_only: true,
      name: "Autumn Group",
      destination: "Dubai",
      travel_date: "2026-10-01",
      return_date: "2026-10-08",
      timezone: "Asia/Kolkata",
      require_selfie: false,
      allow_files_from_device: false,
      upload_configuration: expect.objectContaining({ passport_enabled: false, passport_required: false }),
    }));
    expect(await screen.findByRole("link", { name: "Open group to import Excel" })).toHaveAttribute("href", "/passports/groups/created-group");
    expect(screen.queryByRole("textbox", { name: "Client upload link" })).not.toBeInTheDocument();
  });

  it("discards invalid hidden collection requirements and prior broadcasts when switching to import mode", async () => {
    const user = userEvent.setup();
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    await user.click(screen.getByRole("switch", { name: "Disable Live Passport Scan" }));
    await user.click(screen.getByRole("switch", { name: "Disable Passport Document Upload" }));
    await user.click(screen.getByRole("switch", { name: "Enable Agent/Employee Code" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Code field label" }), { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: "Select WhatsApp broadcast" }));
    await user.click(screen.getByRole("radio", { name: /^Import data/ }));
    await user.click(screen.getByRole("button", { name: "Create Group" }));

    await waitFor(() => expect(createLink).toHaveBeenCalledTimes(1));
    expect(createLink).toHaveBeenCalledWith(expect.objectContaining({
      import_only: true,
      agent_employee_code_enabled: false,
      custom_details: [],
      custom_questions: [],
      whatsapp_broadcast_group_ids: [],
      matching_fields_by_broadcast: {},
      upload_configuration: expect.objectContaining({ agent_employee_code_label: "Agent/Employee Code" }),
    }));
  });

  it("restores collection validation when switching back from import mode", async () => {
    const user = userEvent.setup();
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    await user.click(screen.getByRole("switch", { name: "Disable Live Passport Scan" }));
    await user.click(screen.getByRole("switch", { name: "Disable Passport Document Upload" }));
    await user.click(screen.getByRole("radio", { name: /^Import data/ }));
    await user.click(screen.getByRole("radio", { name: /^Collect documents/ }));
    await user.click(screen.getByRole("button", { name: "Generate Links" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enable at least one method for Passport.");
    expect(createLink).not.toHaveBeenCalled();
  });

  it("lets staff attach a WhatsApp broadcast and matching fields when creating a group", async () => {
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    fireEvent.click(screen.getByRole("button", { name: "Select WhatsApp broadcast" }));
    fireEvent.click(screen.getByRole("button", { name: "Generate Links" }));
    await waitFor(() => expect(createLink).toHaveBeenCalledWith(expect.objectContaining({
      whatsapp_broadcast_group_ids: [broadcastId],
      matching_fields_by_broadcast: { [broadcastId]: ["phone"] },
    })));
  });

  it("submits renamed optional fields and selected passport pages using the settings shown in the dialog", async () => {
    const user = userEvent.setup();
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    expect(screen.queryByRole("textbox", { name: "Notes" })).not.toBeInTheDocument();
    fillGroupDetails();
    await user.click(screen.getByRole("switch", { name: "Enable Visa Photo" }));
    await user.click(screen.getByRole("switch", { name: "Disable Live Photo Capture" }));
    await user.click(screen.getByRole("checkbox", { name: "Make Visa Photo compulsory" }));
    expect(screen.getByText(/Pages to request/).closest("details")).toHaveAttribute("open");
    await user.click(screen.getByRole("checkbox", { name: /^Passport Front Cover/ }));
    await user.click(screen.getByRole("switch", { name: "Enable Agent/Employee Code" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Code field label" }), { target: { value: "Producer Code" } });
    await user.click(screen.getByRole("checkbox", { name: "Make Agent/Employee Code compulsory" }));
    await user.click(screen.getByRole("button", { name: "Generate Links" }));

    await waitFor(() => expect(createLink).toHaveBeenCalledTimes(1));
    expect(createLink).toHaveBeenCalledWith(expect.objectContaining({
      name: "Autumn Group",
      require_selfie: true,
      agent_employee_code_enabled: true,
      upload_configuration: expect.objectContaining({
        visa_photo_live_capture: false,
        visa_photo_upload: true,
        visa_photo_required: false,
        passport_upload_pages: ["cover", "front", "back"],
        agent_employee_code_label: "Producer Code",
        required_fields: { agent_employee_code: false },
      }),
    }));
    expect(createLink.mock.calls[0][0]).not.toHaveProperty("notes");
    expect(await screen.findByRole("heading", { name: "Links Generated" })).toBeInTheDocument();
  });

  it("blocks creation and explains an enabled section with both methods disabled", async () => {
    const user = userEvent.setup();
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    await user.click(screen.getByRole("switch", { name: "Disable Live Passport Scan" }));
    await user.click(screen.getByRole("switch", { name: "Disable Passport Document Upload" }));
    await user.click(screen.getByRole("button", { name: "Generate Links" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enable at least one method for Passport.");
    expect(createLink).not.toHaveBeenCalled();
  });
});
