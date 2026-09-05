"use client";

import Image from "next/image";
import { useState } from "react";

export function CompactPassportImage({ src, alt }: { src: string; alt: string }) {
  const [portrait, setPortrait] = useState(false);
  return (
    <div
      className="relative max-w-full overflow-hidden rounded-xl bg-slate-100"
      style={{ width: portrait ? 220 : 360, height: portrait ? 300 : 230 }}
      data-orientation={portrait ? "portrait" : "landscape"}
    >
      <Image src={src} alt={alt} fill unoptimized sizes="360px" className="object-contain"
        onLoad={(event) => setPortrait(event.currentTarget.naturalHeight > event.currentTarget.naturalWidth)} />
    </div>
  );
}

export function PassportCoverPreview({ url, label, clientName }: {
  url?: string | null; label: string; clientName: string;
}) {
  if (!url) return null;
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold text-slate-700">{label}</h3>
      <a href={url} target="_blank" rel="noreferrer"
        aria-label={`Open ${label} for ${clientName} in a new tab`}
        className="inline-block max-w-full rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">
        <CompactPassportImage src={url} alt={`${label} for ${clientName}`} />
      </a>
    </section>
  );
}
