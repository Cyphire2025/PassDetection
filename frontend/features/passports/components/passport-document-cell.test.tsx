import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fetchDocumentThumbnail } from "../services/document-thumbnail-loader";
import { DeferredDocumentThumbnail } from "./passport-document-cell";

vi.mock("../services/document-thumbnail-loader", () => ({ fetchDocumentThumbnail: vi.fn() }));

const url = "/api/v1/passports/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/images/passport_cover?crop_revision=2";
const originalUrl = URL;
const createObjectURL = vi.fn(() => "blob:cover-preview");
const revokeObjectURL = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("IntersectionObserver", undefined);
  vi.stubGlobal("URL", class extends originalUrl {
    static createObjectURL = createObjectURL;
    static revokeObjectURL = revokeObjectURL;
  });
});
afterEach(() => vi.unstubAllGlobals());

it("uses an authenticated thumbnail while Open keeps the full image URL, then revokes the blob", async () => {
  vi.mocked(fetchDocumentThumbnail).mockResolvedValue(new Blob(["cover"], { type: "image/jpeg" }));
  const view = render(<DeferredDocumentThumbnail url={url} label="Passport Front Cover" />);
  expect(await screen.findByRole("img", { name: "Passport Front Cover" })).toHaveAttribute("src", "blob:cover-preview");
  expect(screen.getByRole("link")).toHaveAttribute("href", url);
  expect(fetchDocumentThumbnail).toHaveBeenCalledWith(url.replace("?", "/thumbnail?"), expect.any(AbortSignal));
  view.unmount();
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:cover-preview");
});

it("offers a retry after failure and replaces it with the recovered image", async () => {
  vi.mocked(fetchDocumentThumbnail)
    .mockRejectedValueOnce(new Error("temporary failure"))
    .mockResolvedValueOnce(new Blob(["cover"], { type: "image/jpeg" }));
  render(<DeferredDocumentThumbnail url={url} label="Passport Back Cover" />);
  fireEvent.click(await screen.findByRole("button", { name: "Retry Passport Back Cover preview" }));
  expect(await screen.findByRole("img", { name: "Passport Back Cover" })).toBeInTheDocument();
  expect(fetchDocumentThumbnail).toHaveBeenCalledTimes(2);
});

it("aborts unmounted previews and discards late results without creating blob URLs", async () => {
  let resolve: (blob: Blob) => void = () => undefined;
  vi.mocked(fetchDocumentThumbnail).mockReturnValue(new Promise<Blob>((done) => { resolve = done; }));
  const view = render(<DeferredDocumentThumbnail url={url} label="Cover" />);
  await waitFor(() => expect(fetchDocumentThumbnail).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(fetchDocumentThumbnail).mock.calls[0][1];
  view.unmount();
  expect(signal.aborted).toBe(true);
  resolve(new Blob(["late"], { type: "image/jpeg" }));
  await Promise.resolve();
  expect(createObjectURL).not.toHaveBeenCalled();
});
