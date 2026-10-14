import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TravellerPortal } from "@/features/upload/components/traveller-portal";
import { returningApi } from "../api/returning.api";
import type { ReturningCapabilities, ReturningMethod } from "../types";
import { ReturningTravellerOffer } from "./returning-offer";

vi.mock("../api/returning.api", () => ({ returningApi: { capabilities: vi.fn() } }));
vi.mock("@/features/passports/hooks/use-upload-links", () => ({ useUploadLinkByToken: () => ({ data: { name: "Synthetic trip" }, isLoading: false, error: null }) }));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
const enabled = { enabled: true, code_label: "Staff code" };
const clients: QueryClient[] = [];
function setup(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } }); clients.push(client);
  return { ...render(<QueryClientProvider client={client}>{children}</QueryClientProvider>), client };
}
function deferred() {
  let resolve!: (value: ReturningCapabilities) => void;
  const promise = new Promise<ReturningCapabilities>((done) => { resolve = done; });
  vi.mocked(returningApi.capabilities).mockReturnValueOnce(promise);
  return resolve;
}
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); vi.mocked(returningApi.capabilities).mockResolvedValue(enabled); });
afterEach(() => { clients.splice(0).forEach((client) => client.clear()); });

describe("returning verification menu availability", () => {
  it("warms availability on the welcome page and reuses it across navigation", async () => {
    const resolve = deferred(); const { client } = setup(<TravellerPortal token="trip" />);
    expect(returningApi.capabilities).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /WhatsApp OTP/ })).not.toBeInTheDocument();
    await act(async () => { resolve(enabled); });
    await waitFor(() => expect(client.getQueryData(["returning-capabilities", "trip"])).toEqual(enabled));
    fireEvent.click(screen.getByRole("button", { name: /^Travelled with us before/ }));
    expect(screen.getByRole("button", { name: /WhatsApp OTP/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Passport number/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Agent \/ employee code/ })).toBeEnabled();
    expect(screen.queryByText("Checking saved-document options…")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: /^Travelled with us before/ }));
    expect(returningApi.capabilities).toHaveBeenCalledOnce();
  });

  it("shows all three choices immediately even when the welcome check has not finished", () => {
    deferred(); setup(<TravellerPortal token="trip" />);
    fireEvent.click(screen.getByRole("button", { name: /^Travelled with us before/ }));
    expect(screen.getByRole("button", { name: /WhatsApp OTP/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Passport number/ })).toBeEnabled();
    expect(screen.getByRole("button", { name: /Agent \/ employee code/ })).toBeEnabled();
    expect(screen.queryByText("Checking saved-document options…")).not.toBeInTheDocument();
    expect(returningApi.capabilities).toHaveBeenCalledOnce();
  });

  it.each<[ReturningMethod, RegExp]>([["phone", /WhatsApp OTP/], ["passport", /Passport number/], ["code", /Agent \/ employee code/]])("queues %s once until server availability is confirmed", async (method, label) => {
    const resolve = deferred(), onSelect = vi.fn();
    setup(<ReturningTravellerOffer token="trip" onSelect={onSelect} />);
    const button = screen.getByRole("button", { name: label });
    fireEvent.click(button); fireEvent.click(button);
    expect(button).toBeDisabled(); expect(button).toHaveAttribute("aria-busy", "true");
    expect(onSelect).not.toHaveBeenCalled(); expect(returningApi.capabilities).toHaveBeenCalledOnce();
    await act(async () => { resolve(enabled); });
    await waitFor(() => expect(onSelect).toHaveBeenCalledExactlyOnceWith(method, enabled));
  });

  it("does not continue a queued selection after Back or leaving the menu", async () => {
    const resolve = deferred(), onSelect = vi.fn();
    const { unmount } = setup(<ReturningTravellerOffer token="trip" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Passport number/ }));
    unmount(); await act(async () => { resolve(enabled); });
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("honours a disabled link instead of navigating a queued option", async () => {
    const resolve = deferred(), onSelect = vi.fn(), onFresh = vi.fn();
    setup(<ReturningTravellerOffer token="trip" onSelect={onSelect} onFresh={onFresh} />);
    fireEvent.click(screen.getByRole("button", { name: /Passport number/ }));
    await act(async () => { resolve({ enabled: false, code_label: null }); });
    await screen.findByRole("heading", { name: "Upload documents for this trip" });
    expect(onSelect).not.toHaveBeenCalled(); expect(screen.queryByRole("button", { name: /WhatsApp OTP/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue as a new traveller" })); expect(onFresh).toHaveBeenCalledOnce();
  });

  it("does not offer or start an individual-code method that the server has disabled", async () => {
    const resolve = deferred(), onSelect = vi.fn(); setup(<ReturningTravellerOffer token="trip" onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /Agent \/ employee code/ }));
    await act(async () => { resolve({ enabled: true, code_label: null }); });
    expect(await screen.findByRole("status")).toHaveTextContent("Code verification is not enabled");
    expect(screen.queryByRole("button", { name: /Agent \/ employee code/ })).not.toBeInTheDocument(); expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Passport number/ }));
    expect(onSelect).toHaveBeenCalledExactlyOnceWith("passport", { enabled: true, code_label: null });
  });

  it("offers a retry after a connection error without treating it as a disabled link", async () => {
    vi.mocked(returningApi.capabilities).mockRejectedValueOnce(new Error("offline"));
    const onSelect = vi.fn(); setup(<ReturningTravellerOffer token="trip" onSelect={onSelect} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("We couldn’t connect");
    expect(screen.queryByText(/Saved-document access is not available/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /WhatsApp OTP/ }));
    await waitFor(() => expect(onSelect).toHaveBeenCalledExactlyOnceWith("phone", enabled));
    expect(returningApi.capabilities).toHaveBeenCalledTimes(2);
  });
});
