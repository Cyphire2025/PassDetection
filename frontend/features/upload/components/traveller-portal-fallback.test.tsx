import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TravellerPortal } from "./traveller-portal";

const api = vi.hoisted(() => ({ lookup: vi.fn() }));
vi.mock("@/features/passports/api/upload-links.api", () => ({ uploadLinksApi: { getByToken: api.lookup } }));
vi.mock("@/features/travellers/hooks/use-returning-capabilities", () => ({ useReturningCapabilities: vi.fn() }));
vi.mock("@/features/travellers/components/returning-offer", () => ({ ReturningTravellerOffer: () => null }));

const token = "synthetic-error-boundary";
const legacyKey = `gct:upload-recovery:${token}`, currentKey = `gc.traveller.draft.v1:${token}`;
const group = { name: "Reopened synthetic trip" };
beforeEach(() => { vi.resetAllMocks(); sessionStorage.clear(); localStorage.clear(); });

function setup(client = new QueryClient()) {
  const view = render(<QueryClientProvider client={client}><TravellerPortal token={token} /></QueryClientProvider>);
  return { dispose: () => { view.unmount(); client.clear(); } };
}

describe("one public link query owns the portal error boundary", () => {
  it.each([
    { error: { status: 404 }, title: "Link Unavailable" },
    { error: { status: 410, code: "CLIENT_GROUP_CLOSED" }, title: "This link is closed." },
    { error: null, title: "Unable to open this link" },
  ])("preserves credentials and retries $title through the primary query", async ({ error, title }) => {
    sessionStorage.setItem(legacyKey, "opaque-legacy-recovery"); localStorage.setItem(currentKey, "opaque-navigation-metadata");
    if (error) api.lookup.mockRejectedValueOnce(error); else api.lookup.mockResolvedValueOnce(null);
    api.lookup.mockResolvedValueOnce(group);
    const view = setup();
    try {
      expect(await screen.findByRole("alert", { name: title })).toBeInTheDocument();
      expect(api.lookup).toHaveBeenCalledExactlyOnceWith(token);
      expect(screen.queryByRole("button", { name: "Only me" })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Full name")).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: error ? "Check again" : "Retry" }));
      await screen.findByRole("button", { name: /^New traveller/ });
      expect(api.lookup).toHaveBeenCalledTimes(2);
      expect(sessionStorage.getItem(legacyKey)).toBe("opaque-legacy-recovery");
      expect(localStorage.getItem(currentKey)).toBe("opaque-navigation-metadata");
    } finally { view.dispose(); }
  });

  it("uses the same error boundary when a failed refresh still has cached group data", async () => {
    const client = new QueryClient();
    client.setQueryData(["upload-links", "token", token], group);
    api.lookup.mockRejectedValueOnce({ status: 404 });
    const view = setup(client);
    try {
      await screen.findByRole("alert", { name: "Link Unavailable" });
      expect(api.lookup).toHaveBeenCalledOnce();
      expect(screen.queryByRole("button", { name: /^New traveller/ })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Full name")).not.toBeInTheDocument();
    } finally { view.dispose(); }
  });
});
