import type { PassportFrameStatus, PassportPageSide } from "./passport-camera-guide";

export function passportFrameGuidance(
  status: PassportFrameStatus,
  pageSide: PassportPageSide,
): string {
  switch (status) {
    case "checking":
      return "Hold steady while the passport page is checked";
    case "no_document":
      return pageSide === "front"
        ? "Position the passport information page inside the frame"
        : "Position the passport back page inside the frame";
    case "incomplete_document":
      return "Show all four page corners inside the frame";
    case "too_small":
      return "Move closer while keeping all four corners visible";
    case "sideways":
    case "upside_down":
    case "excessive_skew":
      return "Hold the passport upright and align it inside the frame";
    case "multiple_documents":
      return "Show only one passport page inside the frame";
    case "screen_or_book":
      return pageSide === "front"
        ? "Show the physical passport information page, not a screen or book"
        : "Show the physical passport back page, not a screen or book";
    case "missing_mrz":
    case "not_passport_page":
      return pageSide === "front"
        ? "Show the passport information page with the photo and MRZ"
        : "Show the passport back page with its printed details";
    case "ready":
      return "Passport page detected - hold steady";
  }
}

