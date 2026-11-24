import Image from "next/image";
import type { PassportUploadPage } from "@/features/passports/types/upload-configuration";

export function PassportPageSample({ page }: { page: PassportUploadPage }) {
  const isCover = page === "cover" || page === "back_cover";
  if (isCover) {
    const isFrontCover = page === "cover";
    return <Image
      src={isFrontCover ? "/assets/upload-samples/passport-front-cover.png" : "/assets/upload-samples/passport-back-cover.png"}
      alt={`Passport ${isFrontCover ? "front" : "back"} cover sample`}
      width={isFrontCover ? 964 : 1005}
      height={isFrontCover ? 1292 : 1291}
      sizes="220px"
      className="h-[160px] w-full rounded-xl bg-slate-50 object-contain"
    />;
  }
  // The previous artwork is retained in passport-detail-samples-original.tsx.
  const isPersonalDetails = page === "front";
  return <Image
    src={isPersonalDetails ? "/assets/upload-samples/indian-passport-personal-details.svg" : "/assets/upload-samples/indian-passport-address-details.svg"}
    alt={`Illustrative Indian passport ${isPersonalDetails ? "personal details" : "address and family details"} page — sample only`}
    width={880}
    height={600}
    unoptimized
    className="h-[160px] w-full rounded-xl bg-slate-50 object-contain"
  />;
}
