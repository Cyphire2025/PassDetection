import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fetchDocumentThumbnail } from "../services/document-thumbnail-loader";
import { DeferredDocumentThumbnail } from "./passport-document-cell";
import { DocumentThumbnailCacheProvider } from "./document-thumbnail-cache-provider";

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
  render(
    <DocumentThumbnailCacheProvider>
      <DeferredDocumentThumbnail url={url} label="Passport Back Cover" />
    </DocumentThumbnailCacheProvider>,
  );
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

it("keeps loaded previews through row remounts, and releases them when leaving the page", async () => {
  vi.mocked(fetchDocumentThumbnail).mockResolvedValue(new Blob(["cover"], { type: "image/jpeg" }));
  const page = (show: boolean, pageKey = "group:1") => (
    <DocumentThumbnailCacheProvider key={pageKey}>
      {show && <DeferredDocumentThumbnail url={url} label="Cover" />}
    </DocumentThumbnailCacheProvider>
  );
  const view = render(page(true));
  await screen.findByRole("img", { name: "Cover" });
  view.rerender(page(false));
  expect(revokeObjectURL).not.toHaveBeenCalled();
  view.rerender(page(true));
  expect(screen.getByRole("img", { name: "Cover" })).toBeInTheDocument();
  expect(fetchDocumentThumbnail).toHaveBeenCalledTimes(1);
  view.rerender(page(true, "group:2"));
  await screen.findByRole("img", { name: "Cover" });
  expect(fetchDocumentThumbnail).toHaveBeenCalledTimes(2);
  expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  view.unmount();
  expect(revokeObjectURL).toHaveBeenCalledTimes(2);
});

it("refetches a changed image without reloading another cached document", async () => {
  vi.mocked(fetchDocumentThumbnail).mockResolvedValue(new Blob(["cover"], { type: "image/jpeg" }));
  const back = url.replace("passport_cover", "passport_back_cover");
  const page = (editedUrl: string) => (
    <DocumentThumbnailCacheProvider>
      <DeferredDocumentThumbnail key={editedUrl} url={editedUrl} label="Front cover" />
      <DeferredDocumentThumbnail url={back} label="Back cover" />
    </DocumentThumbnailCacheProvider>
  );
  const view = render(page(url));
  await screen.findByRole("img", { name: "Front cover" });
  const otherImage = await screen.findByRole("img", { name: "Back cover" });
  view.rerender(page(`${url}&ui_edit_revision=1`));
  await screen.findByRole("img", { name: "Front cover" });
  expect(screen.getByRole("img", { name: "Back cover" })).toBe(otherImage);
  expect(fetchDocumentThumbnail).toHaveBeenCalledTimes(3);
  expect(vi.mocked(fetchDocumentThumbnail).mock.calls.filter(([request]) => request.includes("passport_back_cover"))).toHaveLength(1);
});

it("lets an in-flight preview finish across row remounts, but aborts it on page exit", async () => {
  let resolve: (blob: Blob) => void = () => undefined;
  vi.mocked(fetchDocumentThumbnail).mockReturnValue(new Promise<Blob>((done) => { resolve = done; }));
  const page = (show: boolean) => (
    <DocumentThumbnailCacheProvider>
      {show && <DeferredDocumentThumbnail url={url} label="Cover" />}
    </DocumentThumbnailCacheProvider>
  );
  const view = render(page(true));
  await waitFor(() => expect(fetchDocumentThumbnail).toHaveBeenCalledTimes(1));
  const signal = vi.mocked(fetchDocumentThumbnail).mock.calls[0][1];
  view.rerender(page(false));
  expect(signal.aborted).toBe(false);
  view.rerender(page(true));
  await waitFor(() => expect(screen.getByLabelText("Loading preview")).toBeInTheDocument());
  expect(fetchDocumentThumbnail).toHaveBeenCalledTimes(1);
  view.unmount();
  expect(signal.aborted).toBe(true);
  resolve(new Blob(["late"], { type: "image/jpeg" }));
  await Promise.resolve();
  expect(createObjectURL).not.toHaveBeenCalled();
});

it("discards a cached image that cannot be decoded so Retry can fetch it again", async () => {
  vi.mocked(fetchDocumentThumbnail).mockResolvedValue(new Blob(["cover"], { type: "image/jpeg" }));
  render(
    <DocumentThumbnailCacheProvider>
      <DeferredDocumentThumbnail url={url} label="Cover" />
    </DocumentThumbnailCacheProvider>,
  );
  fireEvent.error(await screen.findByRole("img", { name: "Cover" }));
  expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Retry Cover preview" }));
  await screen.findByRole("img", { name: "Cover" });
  expect(fetchDocumentThumbnail).toHaveBeenCalledTimes(2);
});
