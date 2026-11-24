import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import type { WhatsAppTemplateSettings } from "../whatsapp-template-settings";
import { WhatsAppTemplateSettingsPanel } from "./whatsapp-template-settings-panel";

vi.mock("@/lib/api/client", () => ({ default: { get: vi.fn(), put: vi.fn() } }));
const saved: WhatsAppTemplateSettings = {
  revision: 7, can_edit: true, updated_at: "2026-01-01T00:00:00Z",
  templates: [{ key: "welcome", label: "Welcome message", environment_name: "welcome_default",
    override_name: null, effective_name: "welcome_default", language: "en", source: "environment",
    contract_description: "Synthetic approved template" }],
};
const clients: QueryClient[] = [];
beforeEach(() => {
  vi.mocked(apiClient.get).mockReset().mockResolvedValue({ data: saved });
  vi.mocked(apiClient.put).mockReset().mockResolvedValue({ data: { ...saved, revision: 8 } });
  useAuthStore.setState({ user: { id: "synthetic-template-admin", role: "super_admin", agency_id: null } as User });
});
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
});
function mount(active = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  return { ...render(<QueryClientProvider client={client}><WhatsAppTemplateSettingsPanel active={active} /></QueryClientProvider>), client };
}

it.each(["agency_admin", "agency_staff"])("keeps %s from editing platform-wide template names", async (role) => {
  useAuthStore.setState({ user: { id: "synthetic-template-admin", role, agency_id: "synthetic-agency" } as User });
  mount();
  if (role === "agency_admin") {
    expect(await screen.findByRole("textbox", { name: "Welcome message" })).toBeDisabled();
  } else {
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalled();
  }
  expect(screen.queryByRole("button", { name: "Save template settings" })).not.toBeInTheDocument();
  expect(apiClient.put).not.toHaveBeenCalled();
});

it("loads templates on demand and blocks writes until authoritative values arrive", () => {
  mount(false);
  expect(apiClient.get).not.toHaveBeenCalled();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(apiClient.put).not.toHaveBeenCalled();
});

it("validates names, binds the reviewed revision and admits one pending save", async () => {
  let complete: ((result: { data: WhatsAppTemplateSettings }) => void) | undefined;
  vi.mocked(apiClient.put).mockImplementation(() => new Promise(resolve => { complete = resolve; }));
  mount();
  const input = await screen.findByRole("textbox", { name: "Welcome message" });
  fireEvent.change(input, { target: { value: "Invalid Name" } });
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("button", { name: "Save template settings" })).toBeDisabled();
  fireEvent.change(input, { target: { value: "welcome_new" } });
  const button = screen.getByRole("button", { name: "Save template settings" });
  act(() => { button.click(); button.click(); });
  await waitFor(() => expect(apiClient.put).toHaveBeenCalledTimes(1));
  expect(apiClient.put).toHaveBeenCalledWith("/api/v1/admin/whatsapp-templates", {
    expected_revision: 7, overrides: { welcome: "welcome_new" },
  }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
  await act(async () => complete?.({ data: { ...saved, revision: 8, templates: [{ ...saved.templates[0], override_name: "welcome_new", effective_name: "welcome_new" }] } }));
  expect(await screen.findByText("Template settings saved. New sends will use these names.")).toBeInTheDocument();
  expect(input).toHaveValue("welcome_new");
});

it("keeps a conflicting draft and requires an explicit successful reload before editing again", async () => {
  vi.mocked(apiClient.put).mockRejectedValue({ status: 409, code: "WHATSAPP_TEMPLATE_REVISION_CONFLICT" });
  mount();
  const input = await screen.findByRole("textbox", { name: "Welcome message" });
  fireEvent.change(input, { target: { value: "welcome_draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Save template settings" }));
  await screen.findByText(/Template settings changed since you opened them/);
  expect(input).toHaveValue("welcome_draft");
  expect(input).toBeDisabled();
  vi.mocked(apiClient.get).mockRejectedValueOnce(new Error("Synthetic reload failure"));
  fireEvent.click(screen.getByRole("button", { name: "Reload latest values" }));
  await screen.findByText("Could not reload template settings. Your changes are still here.");
  expect(input).toHaveValue("welcome_draft");
  vi.mocked(apiClient.get).mockResolvedValue({ data: { ...saved, revision: 9 } });
  fireEvent.click(screen.getByRole("button", { name: "Reload latest values" }));
  await waitFor(() => expect(input).toHaveValue("welcome_default"));
  expect(input).toBeEnabled();
});

it("does not let an older authoritative refresh replace a newer cached revision", async () => {
  const { client } = mount();
  const input = await screen.findByRole("textbox", { name: "Welcome message" });
  const newer = { ...saved, revision: 12, templates: [{ ...saved.templates[0], environment_name: "newer_default", effective_name: "newer_default" }] };
  act(() => client.setQueryData(["settings", "whatsapp-templates", "synthetic-template-admin", "super_admin"], newer));
  await waitFor(() => expect(input).toHaveValue("newer_default"));
  fireEvent.click(screen.getByRole("button", { name: "Reload latest values" }));
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  expect(input).toHaveValue("newer_default");
});

it("restores environment fallback with a null override instead of submitting the displayed default", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ data: { ...saved, templates: [{ ...saved.templates[0], override_name: "saved_override", effective_name: "saved_override" }] } });
  mount();
  const input = await screen.findByRole("textbox", { name: "Welcome message" });
  expect(input).toHaveValue("saved_override");
  fireEvent.click(screen.getByRole("button", { name: "Use environment default" }));
  expect(input).toHaveValue("welcome_default");
  fireEvent.click(screen.getByRole("button", { name: "Save template settings" }));
  await waitFor(() => expect(apiClient.put).toHaveBeenCalledWith(expect.any(String), {
    expected_revision: 7, overrides: { welcome: null },
  }, expect.any(Object)));
});

it("aborts an unmounted save and keeps its late result out of the template cache", async () => {
  let complete: ((result: { data: WhatsAppTemplateSettings }) => void) | undefined;
  vi.mocked(apiClient.put).mockImplementation(() => new Promise(resolve => { complete = resolve; }));
  const { client, unmount } = mount();
  fireEvent.change(await screen.findByRole("textbox", { name: "Welcome message" }), { target: { value: "late_draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Save template settings" }));
  await waitFor(() => expect(apiClient.put).toHaveBeenCalledTimes(1));
  const config = vi.mocked(apiClient.put).mock.calls[0][2];
  unmount();
  expect(config?.signal?.aborted).toBe(true);
  await act(async () => complete?.({ data: { ...saved, revision: 99 } }));
  expect(client.getQueryData<WhatsAppTemplateSettings>(["settings", "whatsapp-templates", "synthetic-template-admin", "super_admin"])?.revision).toBe(7);
});

it.each(["actor", "role"])("admits no old draft after the %s changes while query cancellation is pending", async (transition) => {
  const { client } = mount();
  fireEvent.change(await screen.findByRole("textbox", { name: "Welcome message" }), { target: { value: "old_authority_draft" } });
  let release: (() => void) | undefined;
  vi.spyOn(client, "cancelQueries").mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "Save template settings" }));
  await waitFor(() => expect(release).toBeDefined());
  await act(async () => {
    const current = useAuthStore.getState().user!;
    useAuthStore.setState({ user: transition === "actor" ? { ...current, id: "other-synthetic-admin" } : { ...current, role: "agency_admin", agency_id: "synthetic-agency" } });
    release?.();
  });
  expect(apiClient.put).not.toHaveBeenCalled();
  expect(screen.queryByText("Template settings saved. New sends will use these names.")).not.toBeInTheDocument();
});

it("preserves a pending reviewed save across profile refresh for the same authority", async () => {
  const { client } = mount();
  fireEvent.change(await screen.findByRole("textbox", { name: "Welcome message" }), { target: { value: "same_authority_draft" } });
  let release: (() => void) | undefined;
  vi.spyOn(client, "cancelQueries").mockImplementationOnce(() => new Promise<void>(resolve => { release = resolve; }));
  fireEvent.click(screen.getByRole("button", { name: "Save template settings" }));
  await waitFor(() => expect(release).toBeDefined());
  await act(async () => {
    useAuthStore.setState({ user: { ...useAuthStore.getState().user!, full_name: "Updated synthetic profile" } });
    release?.();
  });
  expect(apiClient.put).toHaveBeenCalledTimes(1);
  expect(await screen.findByText("Template settings saved. New sends will use these names.")).toBeInTheDocument();
});
