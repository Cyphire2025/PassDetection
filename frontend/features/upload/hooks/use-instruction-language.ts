"use client";

import { useCallback, useMemo, useState, useSyncExternalStore } from "react";
import { INSTRUCTION_LANGUAGE_CODES, type InstructionLanguage } from "@/features/passports/types/instruction-language";
import type { UploadConfiguration } from "@/features/passports/types/upload-configuration";

const CHANGE_EVENT = "passdetection:instruction-language-change";
const storageKey = (token: string) => `passdetection:instruction-language:${token}`;
const subscribe = (listener: () => void) => {
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
};
const serverLanguage = () => "en";

export interface InstructionLanguageControl {
  language: InstructionLanguage;
  availableLanguages: readonly InstructionLanguage[];
  setLanguage: (language: InstructionLanguage) => void;
}

export function availableInstructionLanguages(config: Pick<UploadConfiguration, "instruction_languages_enabled" | "instruction_languages">): InstructionLanguage[] {
  return config.instruction_languages_enabled
    ? ["en", ...INSTRUCTION_LANGUAGE_CODES.filter((language) => config.instruction_languages.includes(language))]
    : ["en"];
}

/** The preference belongs to one upload link and survives moving between its steps. */
export function useInstructionLanguage(token: string, config: UploadConfiguration): InstructionLanguageControl {
  const choices = availableInstructionLanguages(config).join(",");
  const availableLanguages = useMemo(() => choices.split(",") as InstructionLanguage[], [choices]);
  const readStored = useCallback(() => {
    try { return sessionStorage.getItem(storageKey(token)) ?? "en"; } catch { return "en"; }
  }, [token]);
  const stored = useSyncExternalStore(subscribe, readStored, serverLanguage);
  // Keep the picker usable even when the browser denies web storage.
  const [selection, setSelection] = useState<{ token: string; language: InstructionLanguage } | null>(null);
  const preferred = selection?.token === token ? selection.language : stored;
  const language = availableLanguages.includes(preferred as InstructionLanguage) ? preferred as InstructionLanguage : "en";
  const setLanguage = useCallback((next: InstructionLanguage) => {
    const chosen = availableLanguages.includes(next) ? next : "en";
    setSelection({ token, language: chosen });
    try { sessionStorage.setItem(storageKey(token), chosen); } catch { /* The in-memory preference remains usable. */ }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, [availableLanguages, token]);
  return { language, availableLanguages, setLanguage };
}
