import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FreshDocumentPreview } from "./fresh-document-preview";

beforeEach(() => {
  vi.stubGlobal("IntersectionObserver", undefined);
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:private-draft-preview"), revokeObjectURL: vi.fn() }));
  vi.clearAllMocks();
});

describe("current private draft image lifecycle", () => {
  it("fetches by the private API, exposes a blob preview and revokes it on exit", async () => {
    const api = { document: vi.fn().mockResolvedValue(new Blob(["synthetic"], { type: "image/jpeg" })) };
    const view = render(<FreshDocumentPreview id="private-asset" label="Passport details" api={api} />);
    expect(await screen.findByRole("img", { name: "Passport details" })).toHaveAttribute("src", "blob:private-draft-preview");
    expect(api.document).toHaveBeenCalledWith("private-asset", expect.any(AbortSignal));
    const signal = api.document.mock.calls[0][1] as AbortSignal;
    view.unmount(); expect(signal.aborted).toBe(true);
    expect(URL.revokeObjectURL).toHaveBeenCalledExactlyOnceWith("blob:private-draft-preview");
  });

  it("rejects non-document media before object URL creation and supports a credentialed retry", async () => {
    const api = { document: vi.fn().mockResolvedValueOnce(new Blob(["<script>untrusted</script>"], { type: "text/html" })).mockResolvedValueOnce(new Blob(["synthetic"], { type: "image/jpeg" })) };
    render(<FreshDocumentPreview id="private-asset" label="Passport details" api={api} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("preview is unavailable");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Retry preview" }));
    await screen.findByRole("img", { name: "Passport details" });
    expect(api.document).toHaveBeenCalledTimes(2);
    expect(api.document.mock.calls.every(call => call[0] === "private-asset")).toBe(true);
    expect((api.document.mock.calls[0][1] as AbortSignal).aborted).toBe(true);
  });

  it("ignores a late private response after navigation and creates no object URL", async () => {
    let finish!: (blob: Blob) => void;
    const api = { document: vi.fn(() => new Promise<Blob>(resolve => { finish = resolve; })) };
    const view = render(<FreshDocumentPreview id="private-asset" label="Passport details" api={api} />);
    await waitFor(() => expect(api.document).toHaveBeenCalledOnce());
    view.unmount();
    await act(async () => finish(new Blob(["late"], { type: "image/jpeg" })));
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
