"use client";

import { useId } from "react";
import { INSTRUCTION_LANGUAGE_OPTIONS, type InstructionLanguage } from "@/features/passports/types/instruction-language";
import type { InstructionLanguageControl } from "../hooks/use-instruction-language";

export function InstructionLanguageSelector({ instructions }: { instructions?: InstructionLanguageControl }) {
  const id = useId();
  if (!instructions || instructions.availableLanguages.length <= 1) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <label htmlFor={id} className="text-xs font-medium text-slate-600">Instruction language</label>
      <select id={id} value={instructions.language} onChange={(event) => instructions.setLanguage(event.target.value as InstructionLanguage)}
        className="h-10 max-w-full rounded-xl border border-slate-300 bg-white px-3 text-sm text-slate-800 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-600">
        {instructions.availableLanguages.map((language) => {
          const option = INSTRUCTION_LANGUAGE_OPTIONS.find((item) => item.code === language);
          return <option key={language} value={language}>{option ? `${option.label} · ${option.nativeLabel}` : "English"}</option>;
        })}
      </select>
    </div>
  );
}
