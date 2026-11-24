import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { returningApi } from "../api/returning.api";
import { returningDraftApi } from "../api/returning-draft.api";
import { TravellerDocument } from "./traveller-document";
vi.mock("../api/returning.api", () => ({ returningApi: { document: vi.fn() } }));
vi.mock("../api/returning-draft.api", () => ({ returningDraftApi: { document: vi.fn() } }));
let enter!: () => void;
const create = vi.fn(() => "blob:synthetic-private-document"), revoke = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("URL", Object.assign(class extends URL {}, { createObjectURL: create, revokeObjectURL: revoke }));
  vi.stubGlobal("IntersectionObserver", class {
    constructor(callback: IntersectionObserverCallback) { enter = () => callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver); }
    observe() {} disconnect() {}
  });
  vi.mocked(returningApi.document).mockResolvedValue(new Blob(["synthetic"], { type: "image/jpeg" }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("waits for visibility, fetches a protected blob and releases its URL on unmount", async () => {
  const view = render(<TravellerDocument id="saved-front" label="Passport details" />);
  expect(returningApi.document).not.toHaveBeenCalled(); act(enter);
  expect(await screen.findByRole("img", { name: "Passport details" })).toHaveAttribute("src", "blob:synthetic-private-document");
  const signal = vi.mocked(returningApi.document).mock.calls[0][1]!; view.unmount();
  expect(signal.aborted).toBe(true); expect(revoke).toHaveBeenCalledExactlyOnceWith("blob:synthetic-private-document");
});
it("uses the current draft ID for temporary PDF previews and never calls the saved document endpoint", async () => {
  vi.mocked(returningDraftApi.document).mockResolvedValue(new Blob(["synthetic-pdf"], { type: "application/pdf" }));
  render(<TravellerDocument id="draft-front" label="Draft passport" draftId="synthetic-draft" temporary />); act(enter);
  await waitFor(() => expect(screen.getByTitle("Draft passport")).toHaveAttribute("src", "blob:synthetic-private-document"));
  expect(returningDraftApi.document).toHaveBeenCalledExactlyOnceWith("draft-front", "synthetic-draft", expect.any(AbortSignal)); expect(returningApi.document).not.toHaveBeenCalled();
});
it("abandons a late blob without creating an object URL", async () => {
  let finish!: (blob: Blob) => void;
  vi.mocked(returningApi.document).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const view = render(<TravellerDocument id="saved-front" label="Passport details" />); act(enter);
  await waitFor(() => expect(returningApi.document).toHaveBeenCalledOnce()); view.unmount();
  await act(async () => { finish(new Blob(["late"], { type: "image/jpeg" })); }); expect(create).not.toHaveBeenCalled();
});
it.each([new Blob([], { type: "image/jpeg" }), new Blob(["unsupported"], { type: "text/html" }), new Blob([new Uint8Array(20 * 1024 * 1024 + 1)], { type: "image/png" })])("rejects empty, unsupported or oversized private previews and permits an explicit retry", async blob => {
  vi.mocked(returningApi.document).mockResolvedValueOnce(blob);
  render(<TravellerDocument id="saved-front" label="Passport details" />); act(enter);
  expect(await screen.findByText("Preview could not be loaded.")).toBeVisible(); expect(create).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Retry preview" }));
  expect(await screen.findByRole("img", { name: "Passport details" })).toBeVisible(); expect(returningApi.document).toHaveBeenCalledTimes(2);
});

it("keeps native image decode errors retryable without accepting a remote URL", async () => {
  render(<TravellerDocument id="saved-front" label="Passport details" />); act(enter);
  fireEvent.error(await screen.findByRole("img", { name: "Passport details" }));
  expect(screen.getByText("Preview could not be loaded.")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Retry preview" }));
  expect(await screen.findByRole("img", { name: "Passport details" })).toHaveAttribute("src", "blob:synthetic-private-document");
});
