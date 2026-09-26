import { describe, expect, it } from "vitest";
import { emptyDocumentBundle } from "./upload-flow-helpers";
import { acceptPassportPage } from "./passport-capture-transition";

describe("passport acquisition transition", () => {
  it.each(["front", "back"] as const)("keeps original %s device bytes and previously selected documents", (side) => {
    const bundle = emptyDocumentBundle();
    const cover = new File(["cover"], "cover.jpg");
    bundle.cover = cover;
    const file = new File(["source"], "passport.heic");
    const next = acceptPassportPage(bundle, file, side, "file");
    expect(next.bundle[side]).toBe(file);
    expect(next.bundle.cover).toBe(cover);
    expect(next.bundle[`${side}ManuallyCropped`]).toBe(false);
    expect(next.nextStep).toBe("METHOD_SELECT");
    expect(bundle[side]).toBeNull();
  });
  it("advances front camera capture to the missing back page", () => {
    const next = acceptPassportPage(emptyDocumentBundle(), new File(["image"], "front.jpg"), "front", "camera");
    expect(next.nextStep).toBe("CAMERA");
    expect(next.scannerPageSide).toBe("back");
    expect(next.bundle.frontSource).toBe("camera");
  });
  it.each(["front", "back"] as const)("returns completed %s camera capture to document selection", (side) => {
    const bundle = emptyDocumentBundle();
    bundle.back = new File(["back"], "back.jpg");
    expect(acceptPassportPage(bundle, new File(["capture"], "capture.jpg"), side, "camera").nextStep).toBe("METHOD_SELECT");
  });
});
