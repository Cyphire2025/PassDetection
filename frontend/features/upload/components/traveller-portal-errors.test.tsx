import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TravellerPortal } from "./traveller-portal";

const lookup = vi.hoisted(() => vi.fn());
vi.mock("@/features/passports/api/upload-links.api", () => ({ uploadLinksApi: { getByToken: lookup } }));
vi.mock("@/features/travellers/hooks/use-returning-capabilities", () => ({ useReturningCapabilities: vi.fn() }));

beforeEach(() => { lookup.mockReset(); localStorage.clear(); });

describe("traveller portal link failures", () => {
  it.each([
    { status: 410, code: "CLIENT_GROUP_CLOSED", heading: "This link is closed." },
    { status: 404, code: "CLIENT_GROUP_NOT_FOUND", heading: "Link Unavailable" },
  ])("keeps $status bounded and reopens only after explicit retry", async ({ status, code, heading }) => {
    lookup.mockRejectedValue({ status, code, message: heading });
    const client = new QueryClient({ defaultOptions: { queries: { gcTime: 0, refetchOnWindowFocus: false } } });
    const view = render(<QueryClientProvider client={client}><TravellerPortal token="synthetic-closed-trip" /></QueryClientProvider>);
    await screen.findByRole("heading", { name: heading });
    // Let mount/refetch notifications settle. A nested observer previously caused
    // hundreds of repeated terminal requests and never showed the error screen.
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 80)); });
    expect(lookup).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /New traveller/ })).not.toBeInTheDocument();
    if (code === "CLIENT_GROUP_CLOSED") expect(screen.getByRole("alert", { name: heading })).not.toHaveTextContent(/expired/i);
    lookup.mockResolvedValue({ name: "Reopened synthetic trip", token: "synthetic-closed-trip" });
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByRole("button", { name: /New traveller/ });
    await waitFor(() => expect(lookup).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("heading", { name: heading })).not.toBeInTheDocument();
    view.unmount(); client.clear();
  });
});
