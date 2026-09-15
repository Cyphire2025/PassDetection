import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { gcAppAdminApi } from "../api/gc-app-admin.api";
import { NotificationAudiencePicker } from "./notification-audience-picker";
import { agencyId, group } from "./notification-test-fixtures";
import type { NotificationAudience } from "./notification-types";

vi.mock("../api/gc-app-admin.api", () => ({ gcAppAdminApi: { listGroups: vi.fn() } }));
const clients: QueryClient[] = [];
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(gcAppAdminApi.listGroups).mockImplementation(async (_agency, params) => ({
    items: params.search ? [] : params.page === 1 ? [group] : [{ ...group, id: "trip-2", name: "Synthetic Beach Trip" }],
    page: params.page, page_size: 20, total: params.search ? 0 : 21, has_next: params.page === 1 && !params.search,
  }));
});
afterEach(() => { cleanup(); clients.splice(0).forEach((client) => client.clear()); });

function Harness() {
  const [audience, setAudience] = useState<NotificationAudience>("selected_groups");
  const [groupIds, setGroupIds] = useState<string[]>([]);
  return <NotificationAudiencePicker agencyId={agencyId} audience={audience} groupIds={groupIds} groupNames={{}} disabled={false} onChange={(next, ids) => { setAudience(next); setGroupIds(ids); }} />;
}
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client);
  render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>);
}

describe("Notification multi-group audience", () => {
  it("keeps selected groups across pages and search without loading the entire agency", async () => {
    setup(); const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: /Synthetic Hill Trip/ }));
    await user.click(screen.getByRole("button", { name: "Next" }));
    await user.click(await screen.findByRole("checkbox", { name: /Synthetic Beach Trip/ }));
    expect(screen.getByText(/2 selected/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove Synthetic Hill Trip" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Find active trips"), { target: { value: "No matching group" } });
    await waitFor(() => expect(gcAppAdminApi.listGroups).toHaveBeenLastCalledWith(agencyId, { page: 1, page_size: 20, search: "No matching group", availability: "active" }, expect.any(AbortSignal)));
    expect(await screen.findByText("No active trips match this search.")).toBeVisible();
    expect(screen.getByText(/2 selected/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove Synthetic Beach Trip" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Remove Synthetic Hill Trip" }));
    expect(screen.getByText(/1 selected/)).toBeVisible();
    expect(gcAppAdminApi.listGroups).toHaveBeenCalledWith(agencyId, expect.objectContaining({ page_size: 20, availability: "active" }), expect.any(AbortSignal));
  });

  it("all-active scope is explicit and clears the selected-group request shape", async () => {
    setup(); const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: /Synthetic Hill Trip/ }));
    await user.click(screen.getByRole("radio", { name: /All active GC App trips/ }));
    expect(screen.queryByLabelText("Find active trips")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: /Specific groups/ }));
    expect(await screen.findByRole("checkbox", { name: /Synthetic Hill Trip/ })).not.toBeChecked();
    expect(screen.getByText(/0 selected/)).toBeVisible();
  });
});
