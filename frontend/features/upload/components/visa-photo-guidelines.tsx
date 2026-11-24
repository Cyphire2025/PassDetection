import { useId } from "react";
import { Camera, Eye, Glasses, Image as ImageIcon, Meh, ScanFace, Sun } from "lucide-react";
import type { InstructionLanguage } from "@/features/passports/types/instruction-language";
import { VISA_PHOTO_GUIDELINES, VISA_PHOTO_GUIDELINE_IDS } from "../config/visa-photo-guidelines";

const GUIDELINE_ICONS = {
  pose: ScanFace,
  expression: Meh,
  eyes: Eye,
  headwear: Glasses,
  lighting: Sun,
  quality: ImageIcon,
} as const;

export function VisaPhotoGuidelines({ language }: { language: InstructionLanguage }) {
  const headingId = useId();
  const copy = VISA_PHOTO_GUIDELINES[language];

  return (
    <section
      aria-labelledby={headingId}
      lang={language}
      dir={language === "ur" ? "rtl" : "ltr"}
      className="min-w-0 border-b border-slate-200 pb-5 sm:col-span-2"
    >
      <h2 id={headingId} className="mb-5 flex items-center gap-2 text-base font-bold text-teal-900">
        <Camera className="h-5 w-5 shrink-0" aria-hidden="true" />
        {copy.heading}
      </h2>
      <ul className="grid grid-cols-1 gap-x-6 gap-y-5 sm:grid-cols-2">
        {VISA_PHOTO_GUIDELINE_IDS.map((id) => {
          const Icon = GUIDELINE_ICONS[id];
          const guideline = copy.items[id];
          return (
            <li key={id} className="flex min-w-0 items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-teal-50 text-teal-800">
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <div className="min-w-0 break-words text-start">
                <h3 className="text-sm font-semibold leading-6 text-teal-950">{guideline.title}</h3>
                <p className="mt-1 text-sm leading-6 text-slate-600">{guideline.description}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
