import type { PassportDocumentBundle } from "../components/upload-flow.types";

/** File selection and live capture retain the same original, uncropped bytes. */
export function acceptPassportPage(
  bundle: PassportDocumentBundle,
  file: File,
  pageSide: "front" | "back",
  source: "camera" | "file",
) {
  const nextBundle: PassportDocumentBundle = {
    ...bundle,
    [pageSide]: file,
    [`${pageSide}Source`]: source,
    [`${pageSide}ManuallyCropped`]: false,
  };
  const needsBackCapture = source === "camera" && pageSide === "front" && !bundle.back;
  return {
    bundle: nextBundle,
    nextStep: needsBackCapture ? "CAMERA" as const : "METHOD_SELECT" as const,
    scannerPageSide: needsBackCapture ? "back" as const : pageSide,
  };
}
