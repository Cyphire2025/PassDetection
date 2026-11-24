import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import { PassportDetailImages } from "./passport-detail-images";
import type { PassportImagePreview } from "./passport-image-preview";

vi.mock("./passport-image-preview", () => ({ PassportImagePreview: (props: ComponentProps<typeof PassportImagePreview>) =>
  <button type="button" data-editable={props.canCrop} data-replaceable={props.canChange}
    onClick={(event) => props.onCrop(event.currentTarget)}>{props.label}</button>,
}));

const passport = { client_name: "Synthetic Traveller", passport_photo_url: "/private/visa",
  image_url: "/private/front", passport_back_url: "/private/back" } as PassportSubmission;
const values = () => ({ imageRevision: 2, canCropPassportImages: true, changingImageType: null,
  imageChangeErrors: {}, handleManualImageChange: vi.fn(), setCropEditor: vi.fn() });

describe("passport detail image sections", () => {
  it("keeps required image placeholders and omits absent optional covers", () => {
    render(<PassportDetailImages {...values()} data={{ ...passport, passport_back_url: null }} />);
    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Passport back" })).toHaveAttribute("data-replaceable", "false");
    expect(screen.queryByRole("button", { name: "Passport Front Cover" })).not.toBeInTheDocument();
  });

  it("routes every cover editor to its own image type and return-focus trigger", () => {
    const value = values();
    render(<PassportDetailImages {...value} data={{ ...passport, passport_cover_url: "/private/cover", passport_back_cover_url: "/private/back-cover" }} />);
    expect(screen.getAllByRole("button")).toHaveLength(5);
    const trigger = screen.getByRole("button", { name: "Passport Back Cover" });
    fireEvent.click(trigger);
    expect(value.setCropEditor).toHaveBeenCalledWith({ imageType: "passport_back_cover", label: "Passport Back Cover", returnFocusTarget: trigger });
  });

  it("preserves view-only access without exposing image mutations", () => {
    render(<PassportDetailImages {...values()} data={passport} canCropPassportImages={false} />);
    for (const button of screen.getAllByRole("button")) {
      expect(button).toHaveAttribute("data-editable", "false");
      expect(button).toHaveAttribute("data-replaceable", "false");
    }
  });
});
