export function VisaPhotoSample() {
  return (
    <figure className="mx-auto w-full max-w-[220px]">
      <h2 className="mb-3 text-sm font-semibold text-slate-800">Photograph sample</h2>
      <svg role="img" aria-label="Illustrated Visa Photo sample showing a centred face, white background and 70–80% face framing"
        viewBox="0 0 220 250" className="block h-[250px] w-[220px] max-w-full">
        <rect x="1" y="1" width="180" height="240" rx="9" fill="#ffffff" stroke="#cbd5e1" />
        <path d="M9 241v-13c15-13 38-23 60-26h42c24 4 46 14 62 27v12Z" fill="#64748b" />
        <path d="M73 182v29c9 12 27 12 36 0v-29Z" fill="#cbd5e1" stroke="#64748b" strokeWidth="1.5" />
        <ellipse cx="40" cy="113" rx="8" ry="19" fill="#e2e8f0" stroke="#64748b" strokeWidth="1.5" />
        <ellipse cx="142" cy="113" rx="8" ry="19" fill="#e2e8f0" stroke="#64748b" strokeWidth="1.5" />
        <path d="M40 78c0-37 20-57 51-57s51 20 51 57v40c0 45-23 83-51 83s-51-38-51-83Z" fill="#e2e8f0" stroke="#64748b" strokeWidth="1.5" />
        <path d="M40 91V77c0-36 20-56 51-56s51 20 51 56v14l-13-19c-22 7-42 4-61-8L49 88Z" fill="#475569" />
        <path d="M56 99q10-5 20 0M106 99q10-5 20 0" fill="none" stroke="#475569" strokeWidth="3" strokeLinecap="round" />
        <ellipse cx="67" cy="111" rx="5" ry="4" fill="#475569" />
        <ellipse cx="115" cy="111" rx="5" ry="4" fill="#475569" />
        <path d="M91 116v25l-7 4h14M75 163q16 4 32 0" fill="none" stroke="#64748b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M185 21h11M185 201h11M192 25v172m-3-168 3-5 3 5m-6 164 3 5 3-5" fill="none" stroke="#2563eb" strokeWidth="1.5" strokeLinecap="round" />
        <text x="208" y="111" textAnchor="middle" transform="rotate(-90 208 111)" fill="#2563eb" fontFamily="sans-serif" fontSize="11" fontWeight="600">70–80%</text>
        <text x="91" y="231" textAnchor="middle" fill="#ffffff" fontFamily="sans-serif" fontSize="11" fontWeight="600" letterSpacing="2">SAMPLE</text>
      </svg>
      <figcaption className="mt-2 space-y-1 text-xs leading-5 text-slate-500">
        <p>Face should fill approximately 70–80% of the photograph.</p>
        <p>Plain white background. Face forward with your full head visible.</p>
      </figcaption>
    </figure>
  );
}
