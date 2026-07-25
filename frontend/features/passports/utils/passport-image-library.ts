import type { PassportImageLibrarySource } from "../api/passports.api";

export const PASSPORT_LIBRARY_IMAGE_MAX_BYTES = 10 * 1024 * 1024;

export const PASSPORT_LIBRARY_IMAGE_ACCEPT = [
  "image/*",
  ".heic",
  ".heif",
  ".avif",
  ".bmp",
  ".tif",
  ".tiff",
].join(",");

const PASSPORT_LIBRARY_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/heif",
  "image/avif",
  "image/bmp",
  "image/tiff",
]);

const PASSPORT_LIBRARY_IMAGE_EXTENSION =
  /\.(?:jpe?g|png|webp|hei[cf]|avif|bmp|tiff?)$/i;

export function validatePassportLibraryImage(
  file: Pick<File, "name" | "size" | "type">,
): string | null {
  if (!file.size) return "The selected image is empty. Choose another file.";
  if (file.size > PASSPORT_LIBRARY_IMAGE_MAX_BYTES) {
    return "The selected image is larger than 10 MB. Choose a smaller image.";
  }
  const hasAllowedType = PASSPORT_LIBRARY_IMAGE_TYPES.has(file.type.toLowerCase());
  const hasAllowedExtension = PASSPORT_LIBRARY_IMAGE_EXTENSION.test(file.name);
  if (!hasAllowedType && !hasAllowedExtension) {
    return "Choose a JPEG, PNG, WebP, HEIC/HEIF, AVIF, BMP, or TIFF image.";
  }
  return null;
}

export function formatPassportImageLibrarySource(
  source: PassportImageLibrarySource,
): string {
  if (source === "original") return "Original";
  if (source === "manual") return "Manual upload";
  return "AI generated";
}
