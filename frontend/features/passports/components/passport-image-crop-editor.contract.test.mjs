import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const editor = readFileSync(
  new URL("./passport-image-crop-editor.tsx", import.meta.url),
  "utf8",
);
const detail = readFileSync(
  new URL("./passport-detail.tsx", import.meta.url),
  "utf8",
);
const api = readFileSync(
  new URL("../api/passports.api.ts", import.meta.url),
  "utf8",
);
const endpoints = readFileSync(
  new URL("../../../lib/api/endpoints.ts", import.meta.url),
  "utf8",
);
const apiClient = readFileSync(
  new URL("../../../lib/api/client.ts", import.meta.url),
  "utf8",
);
const permissions = readFileSync(
  new URL("../utils/passport-image-crop-permissions.ts", import.meta.url),
  "utf8",
);

test("all three passport images expose separate Change, Edit, and effective open-new-tab actions", () => {
  for (const imageType of ["visa_photo", "passport_front", "passport_back"]) {
    assert.match(detail, new RegExp(`imageType="${imageType}"`));
  }
  assert.match(detail, /appendCacheRevision/);
  assert.match(detail, /target="_blank"/);
  assert.match(detail, /PassportImageCropEditor/);
  assert.match(detail, /PASSPORT_LIBRARY_IMAGE_ACCEPT/);
  assert.match(detail, /passportsApi\.getImageCrop/);
  assert.match(detail, /passportsApi\.uploadImageLibraryImage/);
  assert.match(detail, /metadata\.revision/);
  assert.match(detail, /aria-busy=\{isChanging\}/);
  assert.match(detail, /\{isChanging \? "Changing…?" : "Change"\}/);
  assert.match(detail, /<Pencil className="h-[^\"]+ w-[^\"]+" \/> Edit/);
  assert.doesNotMatch(detail, />\s*Crop\s*</);
});

test("crop controls follow server editor roles while view-only coordinators keep effective image access", () => {
  assert.match(permissions, /"agency_coordinator"/);
  assert.match(detail, /canCropPassportImages = canEditPassportImages\(currentUser\?\.role\)/);
  assert.match(detail, /canCrop=\{canCropPassportImages\}/);
  assert.match(detail, /\{effectiveUrl && canCrop && \(/);
  assert.match(detail, /canChange=\{canCropPassportImages && Boolean\(/);
  assert.match(detail, /\{canChange && \(/);
  assert.match(detail, /\{cropEditor && canCropPassportImages && \(/);
  assert.match(detail, /href=\{effectiveUrl\}[\s\S]*?target="_blank"/);
});

test("editor fetches the current full-resolution edit source through the authenticated API", () => {
  assert.match(editor, /passportsApi\.getEditableImage/);
  assert.match(api, /getEditableImage:[\s\S]*?responseType: "blob"/);
  assert.match(api, /editable_source_url: string/);
  assert.match(editor, /currentImageUrl=\{metadata\.cropped_url\}/);
});

test("editor supports pointer, touch, keyboard, rotation, dimming, reset, and focus containment", () => {
  assert.match(editor, /onPointerDown/);
  assert.match(editor, /touch-none/);
  assert.match(editor, /onKeyDown/);
  assert.match(editor, /aria-label={`Resize crop from/);
  assert.match(editor, /rotateCropClockwise/);
  assert.match(editor, /CropShade/);
  assert.match(editor, /Reset edits/);
  assert.match(editor, /event\.key !== "Tab"/);
  assert.match(detail, /returnFocusTarget: HTMLButtonElement/);
  assert.match(detail, /onCrop\(event\.currentTarget\)/);
  assert.match(editor, /returnFocusRef\.current = returnFocusTarget/);
  assert.match(editor, /returnFocusRef\.current\?\.focus\(\)/);
});

test("sharpness and the common library are available for every image while guarded AI editing is Visa-only", () => {
  assert.match(editor, /<SharpnessControl/);
  assert.match(editor, /type="range"/);
  assert.match(editor, /min="1"/);
  assert.match(editor, /max="3"/);
  assert.match(editor, /const isVisaPhoto = imageType === "visa_photo"/);
  assert.match(editor, /activePanel === "ai" && isVisaPhoto/);
  assert.match(editor, /Current Visa photo/);
  assert.match(editor, /AI edit instruction/);
  assert.match(
    editor,
    /Regenerate the image of the person in this image to a studio clicked photo for visa application , it should have a plain white background , keep the current details preserved/,
  );
  assert.match(editor, /activePanel === "library"/);
  assert.match(editor, />\s*Library\s*</);
  assert.match(editor, /<ImageLibraryPanel/);
  assert.match(editor, /Original, manual, and AI-generated images remain available here/);
  assert.match(editor, /formatPassportImageLibrarySource/);
  assert.match(editor, /"Currently in use" : "Use this image"/);
  assert.doesNotMatch(editor, /Saved AI image library/);
  assert.match(editor, /passportsApi\.createVisaAiGenerationJob/);
  assert.match(editor, /passportsApi\.useImageLibraryImage/);
  assert.match(editor, /Saved automatically after generation/);
  assert.match(editor, /Your generated image will appear here/);
  assert.doesNotMatch(editor, /verified image|after verification/);
  assert.doesNotMatch(api, /generated Visa image could not be verified/);
  assert.match(editor, /Use this image/);
  assert.match(editor, /bg-\[#C8CE32\]/);
  assert.match(editor, /text-slate-950/);
  assert.doesNotMatch(editor, /bg-emerald-/);
  assert.match(editor, /const effectiveSharpness = 3/);
  assert.match(endpoints, /images\/\$\{imageType\}\/library/);
  assert.match(api, /listImageLibrary/);
  assert.match(api, /uploadImageLibraryImage/);
  assert.match(api, /useImageLibraryImage/);
  assert.match(endpoints, /visa_photo\/ai-library/);
  assert.match(endpoints, /visa_photo\/ai-jobs/);
  assert.match(api, /createVisaAiGenerationJob/);
  assert.match(api, /getActiveVisaAiGenerationJob/);
  assert.match(api, /getVisaAiGenerationJob/);
});

test("Visa AI jobs enqueue quickly, resume after reopening, and poll until a persisted result exists", () => {
  assert.match(api, /export interface VisaAiGenerationJob/);
  assert.match(api, /"queued"/);
  assert.match(api, /"running"/);
  assert.match(api, /"succeeded"/);
  assert.match(api, /"failed"/);
  assert.match(editor, /getActiveVisaAiGenerationJob/);
  assert.match(editor, /waitForVisaAiGenerationJob/);
  assert.match(editor, /VISA_AI_JOB_POLL_INTERVAL_MS = 2_000/);
  assert.match(editor, /job\.status === "queued" \|\| job\.status === "running"/);
  assert.match(editor, /setLibrary\(\(current\) => \[/);
  assert.match(editor, /setFeaturedGenerationId\(result\.id\)/);
  assert.match(editor, /source: "ai_generated"/);
  assert.match(editor, /mergeImageLibraryItems\(items, current\)/);
});

test("Visa AI polling shows non-cancellable progress while close cleanup and structured errors remain", () => {
  assert.match(editor, /new AbortController\(\)/);
  assert.match(editor, /controller\.signal/);
  assert.match(editor, /role="status" aria-live="polite"/);
  assert.match(editor, /aria-busy="true"/);
  assert.match(editor, /Loader2 className="h-4 w-4 animate-spin"/);
  assert.match(editor, /Generating and saving…/);
  assert.doesNotMatch(editor, /Stop waiting/);
  assert.doesNotMatch(editor, /onCancelGenerate/);
  assert.match(editor, /aiRequestRef\.current\?\.abort\(\)/);
  assert.match(api, /createVisaAiGenerationJob:[\s\S]*?signal\?: AbortSignal/);
  assert.match(api, /getVisaAiGenerationJob:[\s\S]*?signal\?: AbortSignal/);
  assert.match(apiClient, /responseData instanceof Blob/);
  assert.match(apiClient, /JSON\.parse\(await responseData\.text\(\)\)/);
  assert.match(
    editor,
    /typeof error === "object"\s*&& error !== null\s*\) \{/,
  );
  assert.match(editor, /if \("response" in error\)/);
  assert.match(editor, /const message = \(error as \{ message\?: unknown \}\)\.message/);
});

test("returning from AI remounts and redraws the Adjust canvas", () => {
  assert.match(
    editor,
    /\[activePanel, cropRect\.rotation_degrees, imageSize\.width, sharpness, workingObjectUrl\]/,
  );
});

test("crop API supports metadata, optimistic save, and reset", () => {
  assert.match(endpoints, /images\/\$\{imageType\}\/crop/);
  assert.match(api, /source_width: number \| null;/);
  assert.match(api, /source_height: number \| null;/);
  assert.match(api, /expected_revision/);
  assert.match(api, /apiClient\.put<PassportImageCropState>/);
  assert.match(api, /apiClient\.delete<PassportImageCropState>/);
});
