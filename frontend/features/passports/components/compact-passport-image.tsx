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
