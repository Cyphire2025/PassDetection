import assert from "node:assert/strict";
import test from "node:test";
import {
  formatPassportImageLibrarySource,
  PASSPORT_LIBRARY_IMAGE_ACCEPT,
  validatePassportLibraryImage,
} from "./passport-image-library.ts";

test("accepts the canonical image formats used by manual passport replacements", () => {
  for (const file of [
    { name: "front.jpg", type: "image/jpeg", size: 1_000 },
    { name: "back.webp", type: "image/webp", size: 1_000 },
    { name: "photo.heic", type: "", size: 1_000 },
    { name: "scan.tiff", type: "image/tiff", size: 1_000 },
  ]) {
    assert.equal(validatePassportLibraryImage(file), null);
  }
  assert.match(PASSPORT_LIBRARY_IMAGE_ACCEPT, /image\/\*/);
  assert.match(PASSPORT_LIBRARY_IMAGE_ACCEPT, /\.heic/);
});

test("rejects empty, oversized, and unsupported uploads before replacing the preview", () => {
  assert.match(
    validatePassportLibraryImage({ name: "front.jpg", type: "image/jpeg", size: 0 }),
    /empty/,
  );
  assert.match(
    validatePassportLibraryImage({
      name: "front.jpg",
      type: "image/jpeg",
      size: 10 * 1024 * 1024 + 1,
    }),
    /larger than 10 MB/,
  );
  assert.match(
    validatePassportLibraryImage({ name: "front.svg", type: "image/svg+xml", size: 1_000 }),
    /JPEG, PNG, WebP/,
  );
});

test("uses clear source labels for every common-library source", () => {
  assert.equal(formatPassportImageLibrarySource("original"), "Original");
  assert.equal(formatPassportImageLibrarySource("manual"), "Manual upload");
  assert.equal(formatPassportImageLibrarySource("ai_generated"), "AI generated");
});
