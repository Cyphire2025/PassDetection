import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import type { GcCommonDocument } from "../types";
import { CommonDocumentsPanel } from "./common-documents-panel";

afterEach(cleanup);

function renderPanel(overrides: Partial<ComponentProps<typeof CommonDocumentsPanel>> = {}) {
  const props = {
    documents: [], isUploading: false, isUpdating: false, previewingDocumentId: null,
    onUpload: vi.fn().mockResolvedValue(undefined), onPreview: vi.fn().mockResolvedValue(new Blob()),
    onSetPublished: vi.fn().mockResolvedValue(undefined), onReorder: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined), ...overrides,
  };
  return { ...render(<CommonDocumentsPanel {...props} />), props };
}

function document(id: string, dates: Partial<GcCommonDocument> = {}): GcCommonDocument {
  return { id, title: id, category: "travel_tips", filename: `${id}.pdf`, version: 1, is_published: true,
    available_from: null, available_until: null, updated_at: new Date().toISOString(), sort_order: 0, ...dates };
}

describe("Trip documents workflow", () => {
  it("distinguishes published, scheduled, expired, and draft document versions", () => {
    renderPanel({ documents: [document("Current"),
      document("Later", { available_from: new Date(Date.now() + 86_400_000).toISOString() }),
      document("Past", { available_until: new Date(Date.now() - 86_400_000).toISOString() }),
      document("Unpublished", { is_published: false }),
    ] });
    for (const label of ["Published", "Scheduled", "Expired", "Draft"]) expect(screen.getByText(label)).toBeVisible();
  });

  it("keeps the selected file after an upload failure without retrying automatically", async () => {
    const onUpload = vi.fn().mockRejectedValue({ message: "The PDF could not be saved" });
    const view = renderPanel({ onUpload });
    const user = userEvent.setup();
    const upload = view.container.querySelector<HTMLInputElement>("#gc-itinerary-upload input[type=file]")!;
    await user.upload(upload, new File(["synthetic test PDF"], "trip-itinerary.pdf", { type: "application/pdf" }));
    const form = within(view.container.querySelector<HTMLElement>("#gc-itinerary-upload")!);
    await user.click(form.getByRole("button", { name: "Upload as draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The PDF could not be saved");
    expect(form.getByText("trip-itinerary.pdf")).toBeVisible();
    expect(onUpload).toHaveBeenCalledTimes(1);
  });

  it("blocks content mutations while a server refresh is unavailable", async () => {
    const { props, container } = renderPanel({ disabled: true, documents: [document("Current")] });
    const publish = screen.getByRole("button", { name: "Unpublish" });
    expect(publish).toBeDisabled();
    expect(container.querySelector<HTMLInputElement>("input[type=file]")).toBeDisabled();
    await userEvent.setup().click(publish);
    expect(props.onSetPublished).not.toHaveBeenCalled();
  });
});
