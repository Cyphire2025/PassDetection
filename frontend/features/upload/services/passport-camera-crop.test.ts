import { expect, it } from "vitest";
import { addCaptureMargin, getVisibleGuideCrop } from "./passport-camera-crop";

function element(bounds: DOMRect) {
  return { getBoundingClientRect: () => bounds };
}

it("maps the visible guide through centered object-cover cropping", () => {
  const video = { ...element({ left: 10, top: 20, width: 400, height: 400 } as DOMRect), videoWidth: 1920, videoHeight: 1080 } as HTMLVideoElement;
  const guide = element({ left: 50, top: 120, width: 320, height: 200 } as DOMRect) as HTMLDivElement;
  const crop = getVisibleGuideCrop(video, guide);
  expect(crop).toEqual({ left: 528, top: 270, width: 864, height: 540 });
});

it("keeps a one-percent capture margin within the original source", () => {
  expect(addCaptureMargin({ left: 0, top: 0, width: 1000, height: 700 }, 1000, 700)).toEqual({ left: 0, top: 0, width: 1000, height: 700 });
  expect(addCaptureMargin({ left: 100, top: 100, width: 200, height: 100 }, 1000, 700)).toEqual({ left: 98, top: 99, width: 204, height: 102 });
});

it("uses the full source if the guide is unavailable", () => {
  expect(getVisibleGuideCrop({ videoWidth: 1440, videoHeight: 990 } as HTMLVideoElement, null)).toEqual({ left: 0, top: 0, width: 1440, height: 990 });
});
