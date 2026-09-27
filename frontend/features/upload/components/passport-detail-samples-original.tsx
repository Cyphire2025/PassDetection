import { PASSPORT_UPLOAD_PAGES } from "@/features/passports/types/upload-configuration";

// Retained intact at the user's request so either original detail-page sample
// can be restored later without reconstructing its SVG artwork.
export function OriginalPassportDetailSample({ page }: { page: "front" | "back" }) {
  return <svg role="img" aria-label={`Illustration of ${PASSPORT_UPLOAD_PAGES.find((item) => item.id === page)?.label}`} viewBox="0 0 220 160" className="h-[160px] w-full rounded-xl bg-slate-50">
      <rect x="9" y="18" width="202" height="123" rx="5" fill="#eef3ea" stroke="#b9c6b6" />
      <text x="24" y="37" fill="#52634d" fontFamily="sans-serif" fontSize="8">{page === "front" ? "PERSONAL DETAILS" : "ADDRESS AND OTHER PARTICULARS"}</text>
      {page === "front" ? <><rect x="22" y="47" width="46" height="56" rx="3" fill="#cbd5e1" /><circle cx="45" cy="63" r="8" fill="#94a3b8" /><path d="M29 94q2-22 16-22t16 22" fill="#94a3b8" />{[52,66,80,94].map((y) => <rect key={y} x="81" y={y} width={y % 3 ? 108 : 71} height="4" rx="2" fill="#a4b3a0" />)}<text x="22" y="119" fill="#72826c" fontSize="8" fontFamily="monospace">P&lt;SAMPLE&lt;PERSON&lt;&lt;&lt;&lt;&lt;&lt;&lt;</text><text x="22" y="130" fill="#72826c" fontSize="8" fontFamily="monospace">000000000&lt;&lt;&lt;0000000&lt;&lt;&lt;</text></> : [52,65,78,91,104,117].map((y) => <rect key={y} x="24" y={y} width={y % 2 ? 154 : 125} height="4" rx="2" fill="#a4b3a0" />)}
    <text x="110" y="91" textAnchor="middle" transform="rotate(-16 110 80)" fill="#607268" opacity="0.5" fontWeight="bold" fontSize="20" fontFamily="sans-serif">SAMPLE</text>
  </svg>;
}
