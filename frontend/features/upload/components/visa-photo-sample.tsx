import Image from "next/image";

export function VisaPhotoSample() {
  return (
    <figure className="mx-auto w-full max-w-[220px]">
      <h2 className="mb-3 text-sm font-semibold text-slate-800">Photograph sample</h2>
      <Image
        src="/assets/upload-samples/visa-photo.png"
        alt="Visa photo sample showing a centred face against a white background with size and framing guides"
        width={297}
        height={418}
        sizes="220px"
        className="block h-auto w-full"
      />
    </figure>
  );
}
