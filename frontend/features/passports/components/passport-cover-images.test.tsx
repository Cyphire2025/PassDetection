import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import type { PassportImageType } from "../api/passports.api";
import { PassportImagePreview } from "./passport-image-preview";
import { PassportDocumentMatrix } from "./passport-document-matrix";

vi.mock("./compact-passport-image", () => ({
  CompactPassportImage: ({ alt }: { alt: string }) => <span role="img" aria-label={alt} />,
}));
vi.mock("./passport-document-cell", () => ({
  DocumentCell: ({ label, url, onEdit }: { label: string; url: string; onEdit: (trigger: HTMLButtonElement) => void }) => (
    <td><a href={url}>{label}</a><button onClick={(event) => onEdit(event.currentTarget)}>Edit {label}</button></td>
  ),
}));

describe("passport covers", () => {
  it.each([
    ["passport_cover", "Passport Front Cover"],
    ["passport_back_cover", "Passport Back Cover"],
  ] as const)("opens, replaces and edits %s using the shared controls", (imageType, label) => {
    const onChange = vi.fn();
    const onCrop = vi.fn();
    const url = `/api/v1/passports/passenger/images/${imageType}?crop_revision=3`;
    render(<PassportImagePreview label={label} imageType={imageType} url={url} clientName="Traveller"
      revision={1} canCrop canChange changeDisabled={false} isChanging={false}
      onChange={onChange} onCrop={onCrop} />);
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", `${url}&ui_crop_revision=1`);
    const file = new File(["replacement"], "cover.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText(`Choose a replacement ${label} image`), { target: { files: [file] } });
    expect(onChange).toHaveBeenCalledWith(file);
    const edit = screen.getByRole("button", { name: "Edit" });
    fireEvent.click(edit);
    expect(onCrop).toHaveBeenCalledWith(edit);
    expect(edit).toHaveAttribute("data-image-type", imageType);
  });

  it("keeps both cover previews read-only for viewers", () => {
    render(<PassportImagePreview label="Passport Front Cover" imageType="passport_cover" url="/cover"
      clientName="Traveller" revision={0} canCrop={false} canChange={false}
      changeDisabled={false} isChanging={false} onChange={vi.fn()} onCrop={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Open" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  });

  it("includes all five images in DOCS view and edits the correct cover", () => {
    const passport = {
      id: "passenger", client_name: "Traveller", extracted_fields: null, confirmed_fields: null,
      passport_photo_url: "/photo", image_url: "/front", passport_back_url: "/back",
      passport_cover_url: "/front-cover", passport_back_cover_url: "/back-cover",
    } as PassportSubmission;
    const onEdit = vi.fn();
    render(<PassportDocumentMatrix passports={[passport]} canEdit onEdit={onEdit} />);
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader")).toHaveLength(6);
    expect(within(table).getAllByRole("link")).toHaveLength(5);
    const covers: Array<[PassportImageType, string, string]> = [
      ["passport_cover", "Passport Front Cover", "/front-cover"],
      ["passport_back_cover", "Passport Back Cover", "/back-cover"],
    ];
    for (const [type, label, url] of covers) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", url);
      const trigger = screen.getByRole("button", { name: `Edit ${label}` });
      fireEvent.click(trigger);
      expect(onEdit).toHaveBeenLastCalledWith("passenger", type, label, trigger);
    }
  });
});
