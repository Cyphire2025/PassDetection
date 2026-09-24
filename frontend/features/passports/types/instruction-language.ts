export const INSTRUCTION_LANGUAGE_CODES = ["mr", "hi", "te", "kn", "gu", "bn", "or", "ml", "ta", "ur"] as const;
export type AdditionalInstructionLanguage = typeof INSTRUCTION_LANGUAGE_CODES[number];
export type InstructionLanguage = "en" | AdditionalInstructionLanguage;

export const INSTRUCTION_LANGUAGE_OPTIONS: { code: AdditionalInstructionLanguage; label: string; nativeLabel: string }[] = [
  { code: "mr", label: "Marathi", nativeLabel: "मराठी" },
  { code: "hi", label: "Hindi", nativeLabel: "हिन्दी" },
  { code: "te", label: "Telugu", nativeLabel: "తెలుగు" },
  { code: "kn", label: "Kannada", nativeLabel: "ಕನ್ನಡ" },
  { code: "gu", label: "Gujarati", nativeLabel: "ગુજરાતી" },
  { code: "bn", label: "Bengali", nativeLabel: "বাংলা" },
  { code: "or", label: "Odia", nativeLabel: "ଓଡ଼ିଆ" },
  { code: "ml", label: "Malayalam", nativeLabel: "മലയാളം" },
  { code: "ta", label: "Tamil", nativeLabel: "தமிழ்" },
  { code: "ur", label: "Urdu", nativeLabel: "اردو" },
];
