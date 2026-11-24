"use client";
import { Card, CardContent } from "@/components/ui/card";
import { PassportImagePreview } from "./passport-image-preview";
import type { PassportSubmission } from "@/types/passport.types";
import type { PassportDetailController } from "./use-passport-detail-controller";

export const PASSPORT_DETAIL_IMAGES = [
  { imageType: "visa_photo", label: "Visa Photo", field: "passport_photo_url", optional: false },
  { imageType: "passport_cover", label: "Passport Front Cover", field: "passport_cover_url", optional: true },
  { imageType: "passport_back_cover", label: "Passport Back Cover", field: "passport_back_cover_url", optional: true },
  { imageType: "passport_front", label: "Passport front", field: "image_url", optional: false },
  { imageType: "passport_back", label: "Passport back", field: "passport_back_url", optional: false },
] as const;

export function PassportDetailImages({ data, imageRevision, canCropPassportImages, changingImageType,
  imageChangeErrors, handleManualImageChange, setCropEditor }: Pick<PassportDetailController,
    "imageRevision" | "canCropPassportImages" | "changingImageType" | "imageChangeErrors" | "handleManualImageChange" | "setCropEditor"> & { data: PassportSubmission }) {
  return <Card className="overflow-hidden rounded-xl">
    <CardContent className="space-y-5 p-4">
      {PASSPORT_DETAIL_IMAGES.map(({ imageType, label, field, optional }) => {
        const url = data[field];
        if (optional && !url) return null;
        return <PassportImagePreview key={imageType} label={label} imageType={imageType} url={url}
          clientName={data.client_name} revision={imageRevision} canCrop={canCropPassportImages}
          canChange={canCropPassportImages && Boolean(url)} changeDisabled={changingImageType !== null}
          isChanging={changingImageType === imageType} changeError={imageChangeErrors[imageType]}
          onChange={(file) => void handleManualImageChange(imageType, file)}
          onCrop={(returnFocusTarget) => setCropEditor({ imageType, label, returnFocusTarget })} />;
      })}
    </CardContent>
  </Card>;
}
