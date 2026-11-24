"use client";

import { Check, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui";
import type { PassportImageLibraryItem } from "../api/passports.api";

export function VisaAiPanel({
  currentImageUrl,
  library,
  featuredGenerationId,
  prompt,
  busy,
  isGenerating,
  isLoadingLibrary,
  usingImageId,
  onPromptChange,
  onGenerate,
  onUseGeneration,
}: {
  currentImageUrl: string;
  library: PassportImageLibraryItem[];
  featuredGenerationId: string | null;
  prompt: string;
  busy: boolean;
  isGenerating: boolean;
  isLoadingLibrary: boolean;
  usingImageId: string | null;
  onPromptChange: (value: string) => void;
  onGenerate: () => void;
  onUseGeneration: (generationId: string) => void;
}) {
  const featured = library.find((item) => item.id === featuredGenerationId) ?? library[0] ?? null;
  return (
    <div
      id="passport-image-ai-panel"
      role="tabpanel"
      className="flex min-h-[28rem] flex-1 flex-col gap-5"
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)_minmax(0,1fr)] lg:items-center">
      <ImageComparisonCard
        title="Current Visa photo"
        imageUrl={currentImageUrl}
        isCurrent
        isUsing={false}
        disabled
        onUse={() => undefined}
      />
      <div className="rounded-2xl border border-[#C8CE32] bg-white p-4 shadow-sm">
        <label htmlFor="visa-ai-prompt" className="text-sm font-semibold text-slate-900">
          AI edit instruction
        </label>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          Request presentation fixes only, such as a clean white background, balanced exposure, or noise reduction. Identity and biometric features cannot be changed.
        </p>
        <textarea
          id="visa-ai-prompt"
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          disabled={busy}
          maxLength={1000}
          rows={8}
          placeholder="Example: Replace the background with an even plain white studio background and balance the lighting. Preserve the person exactly."
          className="mt-3 w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 outline-none focus:border-[#C8CE32] focus:ring-2 focus:ring-[#C8CE32]/30 disabled:bg-slate-50"
        />
        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
          <span>{prompt.length}/1000</span>
          <span>Saved automatically after generation</span>
        </div>
        {isGenerating ? (
          <div className="mt-4" role="status" aria-live="polite">
            <Button
              type="button"
              aria-busy="true"
              className="w-full gap-2 bg-[#C8CE32] text-slate-950 hover:bg-[#C8CE32] disabled:cursor-wait disabled:opacity-100"
              disabled
            >
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Generating and saving…
            </Button>
          </div>
        ) : (
          <Button
            type="button"
            className="mt-4 w-full gap-2 bg-[#C8CE32] text-slate-950 hover:bg-[#C8CE32] hover:brightness-95"
            disabled={busy || prompt.trim().length < 3}
            onClick={onGenerate}
          >
            <Sparkles className="h-4 w-4" /> Generate and save
          </Button>
        )}
      </div>
      {featured ? (
        <ImageComparisonCard
          title="Latest generated image"
          imageUrl={featured.image_url}
          isCurrent={featured.is_current}
          isUsing={usingImageId === featured.id}
          disabled={busy || featured.is_current}
          onUse={() => onUseGeneration(featured.id)}
        />
      ) : isLoadingLibrary ? (
        <div className="flex min-h-80 items-center justify-center rounded-2xl border border-dashed border-[#C8CE32] bg-[#C8CE32]/10 text-sm font-medium text-slate-800" role="status">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-slate-950" aria-hidden="true" /> Loading saved images
        </div>
      ) : (
        <div className="flex min-h-80 items-center justify-center rounded-2xl border border-dashed border-[#C8CE32] bg-white px-6 text-center text-sm text-slate-500">
          Your generated image will appear here and be saved to the library.
        </div>
      )}
      </div>
    </div>
  );
}

function ImageComparisonCard({
  title,
  imageUrl,
  isCurrent,
  isUsing,
  disabled,
  onUse,
}: {
  title: string;
  imageUrl: string;
  isCurrent: boolean;
  isUsing: boolean;
  disabled: boolean;
  onUse: () => void;
}) {
  return (
    <figure className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <figcaption className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-800">
        {title}
      </figcaption>
      {/* Same-origin endpoints authorize each request and explicitly disable shared caching. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={imageUrl} alt={title} className="max-h-[58vh] w-full bg-slate-100 object-contain" />
      <div className="border-t border-slate-100 p-3">
        <Button
          type="button"
          className="w-full gap-2 bg-[#C8CE32] text-slate-950 hover:bg-[#C8CE32] hover:brightness-95"
          disabled={disabled}
          onClick={onUse}
        >
          {isUsing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          {isCurrent ? "Currently in use" : "Use this image"}
        </Button>
      </div>
    </figure>
  );
}

