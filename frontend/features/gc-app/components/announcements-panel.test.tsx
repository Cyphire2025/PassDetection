import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { AnnouncementsPanel } from "./announcements-panel";

const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

function renderPanel(overrides: Partial<ComponentProps<typeof AnnouncementsPanel>> = {}) {
  const props = {
    agencyId: "agency-1", groupId: "group-1", announcements: [], isCreating: false, isUpdating: false,
    onCreate: vi.fn().mockResolvedValue(undefined), onUpdate: vi.fn().mockResolvedValue(undefined),
    onSetPublished: vi.fn().mockResolvedValue(undefined), onDelete: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const ui = (next = props) => <QueryClientProvider client={client}><AnnouncementsPanel {...next} /></QueryClientProvider>;
  const view = render(ui());
  return { ...view, props, refresh: (patch: Partial<typeof props>) => view.rerender(ui({ ...props, ...patch })) };
}

function enterMessage() {
  fireEvent.change(screen.getByRole("textbox", { name: "Title" }), { target: { value: "Meet in the lobby" } });
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Please arrive at 8 AM." } });
}

describe("Announcement publishing workflow", () => {
  it("saves one draft intent and clears the editor only after success", async () => {
    const { props } = renderPanel();
    enterMessage();
    await userEvent.setup().click(screen.getByRole("button", { name: "Save draft" }));
    expect(props.onCreate).toHaveBeenCalledExactlyOnceWith({
      title: "Meet in the lobby", body: "Please arrive at 8 AM.", priority: "normal",
      available_from: null, available_until: null, publish: false,
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Draft saved");
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("");
  });

  it("submits save-and-publish as one intent and retains the failed draft", async () => {
    const onCreate = vi.fn().mockRejectedValue({ message: "Publishing failed; no changes saved" });
    const { refresh } = renderPanel({ onCreate });
    enterMessage();
    await userEvent.setup().click(screen.getByRole("button", { name: "Publish announcement" }));
    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate.mock.calls[0]?.[0]).toMatchObject({ publish: true });
    expect(await screen.findByRole("alert")).toHaveTextContent("Publishing failed");
    refresh({ disabled: true });
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue("Meet in the lobby");
    expect(screen.getByRole("button", { name: "Publish announcement" })).toBeDisabled();
  });

  it("offers scheduling for a future availability date and sends the exact date", async () => {
    const { props } = renderPanel();
    enterMessage();
    const date = new Date(Date.now() + 86_400_000 * 7);
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
    fireEvent.change(screen.getByLabelText("Available from"), { target: { value: local } });
    await userEvent.setup().click(screen.getByRole("button", { name: "Save & schedule" }));
    expect(props.onCreate).toHaveBeenCalledTimes(1);
    expect(props.onCreate).toHaveBeenCalledWith(expect.objectContaining({ publish: true, available_from: new Date(local).toISOString() }));
  });

  it("labels scheduled and expired publications without promising phone delivery", () => {
    const raw = { body: "Trip update", priority: "normal" as const, is_published: true, version: 1,
      updated_at: new Date().toISOString(), available_from: null, available_until: null };
    renderPanel({ announcements: [
      { ...raw, id: "future", title: "Future update", available_from: new Date(Date.now() + 86_400_000).toISOString() },
      { ...raw, id: "past", title: "Expired update", available_until: new Date(Date.now() - 86_400_000).toISOString() },
    ], total: 27 });
    expect(within(screen.getByRole("article", { name: "Future update" })).getByText("Scheduled")).toBeVisible();
    expect(within(screen.getByRole("article", { name: "Expired update" })).getByText("Expired")).toBeVisible();
    expect(screen.getByText("27 total")).toBeVisible();
    expect(screen.getByText(/Publishing and phone notification delivery are separate/)).toBeVisible();
  });

  it("protects unsaved editor text from selecting a different announcement", async () => {
    renderPanel({ announcements: [{ id: "existing", title: "Existing update", body: "Original text", priority: "normal",
      is_published: false, available_from: null, available_until: null, version: 1, updated_at: new Date().toISOString() }] });
    enterMessage();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole("button", { name: "Discard draft edits" }));
    expect(screen.getByRole("button", { name: "Edit" })).toBeEnabled();
  });
});
