import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const editor = readFileSync(
  new URL("./passport-manual-crop.tsx", import.meta.url),
  "utf8",
);
const flow = readFileSync(
  new URL("./upload-flow.tsx", import.meta.url),
  "utf8",
);

test("manual crop guidance protects the complete passport while removing surroundings", () => {
  assert.match(editor, /Crop out fingers and surrounding background\./);
  assert.match(
    editor,
    /Keep the entire passport page, all four corners, and every detail clearly visible\./,
  );
  assert.match(editor, /Use cropped photo/);
});

test("crop editor is a touch and keyboard accessible modal", () => {
  assert.match(editor, /role="dialog"/);
  assert.match(editor, /aria-modal="true"/);
  assert.match(editor, /touch-none/);
  assert.match(editor, /setPointerCapture/);
  assert.match(editor, /onKeyDown=\{\(event\) => handleCropKeyboard/);
  assert.match(editor, /Resize crop from \$\{cornerLabel\(corner\)\} corner/);
  assert.match(editor, /Rotate 90°/);
  assert.match(editor, /env\(safe-area-inset-bottom\)/);
  assert.match(editor, /event\.key !== "Tab"/);
  assert.match(editor, /dialogRef\.current\?\.querySelectorAll/);
});

test("upload links bypass manual crop while retaining its implementation for later use", () => {
  assert.match(flow, /\| "PASSPORT_CROP"/);
  assert.match(
    flow,
    /const handleCameraCapture = \(file: File\) => \{\s*beginPassportCrop\(file, scannerPageSide, "camera"\);/,
  );
  assert.match(
    flow,
    /onFileSelect=\{\(pageSide, file\) => beginPassportCrop\(file, pageSide, "file"\)\}/,
  );
  assert.match(
    flow,
    /step === "PASSPORT_CROP"[\s\S]*?<PassportManualCrop/,
  );
  assert.match(
    flow,
    /const handlePassportCropConfirm = \([\s\S]*?croppedFile: File,[\s\S]*?manuallyCropped: boolean/,
  );
  assert.match(
    flow,
    /Manual passport cropping is intentionally unwired from upload links/,
  );
  assert.match(
    flow,
    /\[`\$\{pageSide\}ManuallyCropped`\]: false/,
  );
  assert.match(
    flow,
    /source === "camera" && pageSide === "front" && !documentBundle\.back[\s\S]*?setStep\("CAMERA"\)[\s\S]*?setStep\("METHOD_SELECT"\)/,
  );
});

test("the exact cropped JPEG is quality checked before it can leave the editor", () => {
  const createIndex = editor.indexOf("createCroppedPassportFile(");
  const validateIndex = editor.indexOf(
    "validatePassportFinalFile(croppedFile, pageSide)",
    createIndex,
  );
  const confirmIndex = editor.indexOf(
    "onConfirm(croppedFile, true)",
    validateIndex,
  );

  assert.ok(createIndex >= 0);
  assert.ok(validateIndex > createIndex);
  assert.ok(confirmIndex > validateIndex);
  assert.match(editor, /quality\.outcome === "hard_failure"/);
  assert.match(editor, /quality\.outcome === "borderline"/);
  assert.match(editor, /checked=\{borderlineConfirmed\}/);
  assert.match(
    flow,
    /frontSource === "camera" \|\| frontManuallyCropped[\s\S]*?\? file[\s\S]*?: \(await normalizePassportFile\(file\)\)\.file/,
  );
});

test("browser-unsupported image formats can continue through secure server validation", () => {
  assert.match(editor, /setPreviewUnavailable\(true\)/);
  assert.match(editor, /Manual cropping is not available for this photo format/);
  assert.match(editor, /The original will still be checked and converted securely/);
  assert.match(editor, /previewUnavailable[\s\S]*?Use original photo/);
  assert.match(editor, /onConfirm\(file, false\)/);
});
