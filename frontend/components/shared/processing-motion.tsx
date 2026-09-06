"use client";

import { useEffect, useId, useRef, useState } from "react";
import { cn } from "@/lib/utils/cn";
import styles from "./processing-motion.module.css";

export type ProcessingMotionVariant = "passport" | "analysis" | "rename" | "distribution";

/** Decorative activity artwork. The calling workflow owns all status and progress. */
export function ProcessingMotion({ variant, compact = false, className }: {
  variant: ProcessingMotionVariant;
  compact?: boolean;
  className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const root = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(true);

  useEffect(() => {
    let inView = true;
    const update = () => setPlaying(inView && !document.hidden);
    const observer = typeof IntersectionObserver === "undefined" ? null : new IntersectionObserver(
      ([entry]) => { inView = entry.isIntersecting; update(); },
      { threshold: 0 },
    );
    if (root.current) observer?.observe(root.current);
    document.addEventListener("visibilitychange", update);
    update();
    return () => {
      observer?.disconnect();
      document.removeEventListener("visibilitychange", update);
    };
  }, []);

  return (
    <div
      ref={root}
      aria-hidden="true"
      data-processing-motion={variant}
      data-playing={playing}
      className={cn(styles.scene, compact && styles.compact, className)}
    >
      <svg viewBox="0 0 520 280" fill="none" focusable="false" className={styles.artwork}>
        <defs>
          <linearGradient id={`${id}-paper`} x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#FFFFFF" /><stop offset="1" stopColor="#E6F0F5" />
          </linearGradient>
          <linearGradient id={`${id}-cover`} x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#2279A4" /><stop offset="1" stopColor="#0B304E" />
          </linearGradient>
          <linearGradient id={`${id}-metal`} x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="#DEE9ED" /><stop offset="1" stopColor="#A9C1CC" />
          </linearGradient>
          <linearGradient id={`${id}-beam`} x1="0" y1="0" x2="0" y2="1">
            <stop stopColor="#38AED0" stopOpacity="0" />
            <stop offset="1" stopColor="#38AED0" stopOpacity=".25" />
          </linearGradient>
        </defs>
        <ellipse cx="260" cy="240" rx="172" ry="17" fill="#123F59" opacity=".06" />
        <path d="M71 233H449M91 237H119M401 237H429" stroke="#CDDEE6" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="67" cy="116" r="3" fill="#C5DDE7" />
        <circle cx="443" cy="68" r="4" stroke="#C2D9E4" />
        <path d="M86 56V64M82 60H90M435 180V188M431 184H439" stroke="#B5D15D" strokeWidth="2" strokeLinecap="round" />
        {variant === "passport" ? <PassportScene id={id} />
          : variant === "analysis" ? <AnalysisScene id={id} />
          : variant === "rename" ? <RenameScene id={id} />
          : <DistributionScene id={id} />}
      </svg>
    </div>
  );
}

function Person({ x, y, blue = false }: { x: number; y: number; blue?: boolean }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <rect width="42" height="50" rx="6" fill={blue ? "#E2EFF4" : "#DDE9EF"} />
      <circle cx="21" cy="17" r="8" fill="#7FA4B7" />
      <path d="M7 43C7 25 35 25 35 43" fill="#7FA4B7" />
    </g>
  );
}

function Sheet({ id, x, y, angle = 0, className }: {
  id: string; x: number; y: number; angle?: number; className?: string;
}) {
  return (
    <g transform={`translate(${x} ${y}) rotate(${angle} 58 76)`}>
      <g className={className}>
        <path d="M8 5H91L118 32V149Q118 157 110 157H8Q0 157 0 149V13Q0 5 8 5Z" fill="#C3D5DE" />
        <path d="M8 0H89L114 25V145Q114 153 106 153H8Q0 153 0 145V8Q0 0 8 0Z" fill={`url(#${id}-paper)`} stroke="#A9C5D4" strokeWidth="1.5" />
        <path d="M89 0V19Q89 25 95 25H114" fill="#DCEAF0" stroke="#A9C5D4" strokeWidth="1.5" strokeLinejoin="round" />
        <rect x="15" y="17" width="34" height="22" rx="4" fill="#145B82" />
        <text x="32" y="32" textAnchor="middle" fill="white" fontSize="10" fontWeight="700" fontFamily="Arial, sans-serif">PDF</text>
        <path d="M17 59H77M17 71H95M17 83H85M17 111H95M17 123H67" stroke="#B2CBD7" strokeWidth="4" strokeLinecap="round" />
        <rect x="17" y="93" width="44" height="5" rx="2.5" fill="#A3CB4B" />
        <path d="M77 138H97" stroke="#6599B2" strokeWidth="2" strokeLinecap="round" />
      </g>
    </g>
  );
}

function PassportScene({ id }: { id: string }) {
  return (
    <>
      <g transform="translate(98 57) rotate(-7 119 87)">
        <g className={styles.lift}>
          <path d="M3 8Q3 0 12 0H108L121 6L132 0H232Q241 0 241 9V162Q241 172 231 172H131L121 178L109 172H12Q3 172 3 163Z" fill={`url(#${id}-cover)`} />
          <path d="M15 13H106L120 19V157L106 151H15Z" fill="#1A577B" stroke="#4F8BA6" />
          <path d="M133 12H225V151H133L122 157V19Z" fill={`url(#${id}-paper)`} />
          <path d="M121 21V165" stroke="#092A44" strokeWidth="3" />
          <text x="67" y="39" textAnchor="middle" fontSize="10" fontWeight="700" letterSpacing="1.5" fill="#DAEAF0" fontFamily="Arial, sans-serif">PASSPORT</text>
          <circle cx="67" cy="82" r="26" stroke="#D0E5EF" strokeWidth="1.5" />
          <ellipse cx="67" cy="82" rx="12" ry="26" stroke="#D0E5EF" />
          <path d="M41 82H93M45 68H89M45 96H89" stroke="#D0E5EF" />
          <rect x="55" y="122" width="25" height="13" rx="3" stroke="#A4CD56" />
          <circle cx="67.5" cy="128.5" r="4" stroke="#A4CD56" />
          <Person x={136} y={31} />
          <path d="M187 35H214M187 47H207M187 59H214M137 97H211M137 106H200" stroke="#94B6C7" strokeWidth="3" strokeLinecap="round" />
          <path d="M138 124H215M138 132H215M138 140H215" stroke="#759CAF" strokeWidth="3" strokeDasharray="2 3" />
          <svg x="130" y="22" width="93" height="124" viewBox="0 0 93 124" overflow="hidden">
            <g className={styles.scan}>
              <rect width="93" height="30" fill={`url(#${id}-beam)`} />
              <path d="M0 30H93" stroke="#22A1BB" strokeWidth="2" />
            </g>
          </svg>
          <path d="M130 29V20H142M214 20H224V29M130 140V149H140M214 149H224V140" stroke="#ACD65B" strokeWidth="2" strokeLinecap="round" />
        </g>
      </g>
      <path d="M344 125H365" stroke="#97BDCE" strokeWidth="1.5" strokeDasharray="3 5" />
      <g transform="translate(367 78)">
        {[0, 1, 2].map((index) => (
          <g key={index} transform={`translate(0 ${index * 35})`}>
            <g className={styles.field}>
              <rect width="70" height="27" rx="6" fill="#F3F8FA" stroke="#BED4DE" />
              <rect x="9" y="9" width="8" height="8" rx="2" fill={index === 1 ? "#A7CE52" : "#67A0B9"} />
              <path d="M25 10H57M25 17H47" stroke="#7F9FAF" strokeWidth="2" strokeLinecap="round" />
            </g>
          </g>
        ))}
      </g>
    </>
  );
}

function AnalysisScene({ id }: { id: string }) {
  return (
    <>
      <Sheet id={id} x={143} y={54} angle={-12} />
      <Sheet id={id} x={172} y={50} angle={2} />
      <g transform="translate(179 74)">
        <svg width="104" height="117" viewBox="0 0 104 117" overflow="hidden">
          <g className={styles.scan}>
            <rect width="104" height="25" fill={`url(#${id}-beam)`} />
            <path d="M0 25H104" stroke="#239CB6" strokeWidth="2" />
          </g>
        </svg>
      </g>
      <g className={styles.inspect}>
        <path d="M313 151L352 195" stroke="#0E3F60" strokeWidth="17" strokeLinecap="round" />
        <path d="M318 158L326 167" stroke="#A7D153" strokeWidth="17" />
        <circle cx="284" cy="117" r="49" fill="#EEF7FA" fillOpacity=".93" stroke="#B6CFDA" strokeWidth="9" />
        <circle cx="284" cy="117" r="43" stroke="#185D80" strokeWidth="5" />
        <path d="M260 102H307M260 115H297M260 128H307" stroke="#81ADBF" strokeWidth="5" strokeLinecap="round" />
        <path d="M260 140H284" stroke="#A3CD4B" strokeWidth="5" strokeLinecap="round" />
        <path d="M257 83Q274 69 294 77" stroke="white" strokeWidth="3" strokeLinecap="round" />
      </g>
      <g transform="translate(366 100)">
        <rect width="45" height="61" rx="8" fill="#F7FAFC" stroke="#BED4DE" />
        <path d="M12 17H31M12 28H31M12 39H24" stroke="#87ABBE" strokeWidth="3" strokeLinecap="round" />
        <circle className={styles.beacon} cx="32" cy="49" r="4" fill="#9CC645" />
      </g>
    </>
  );
}

function RenameScene({ id }: { id: string }) {
  return (
    <>
      <path d="M101 191L144 214H353L409 185L401 203L354 228H144L105 207Z" fill={`url(#${id}-metal)`} stroke="#9FBAC7" strokeWidth="1.5" />
      <path d="M104 187L152 166H360L408 185L354 214H145Z" fill="#F0F5F7" stroke="#BACFD9" strokeWidth="1.5" />
      <path d="M148 221H327" stroke="#E5EEF2" strokeWidth="2" />
      <Sheet id={id} x={145} y={43} angle={-10} />
      <Sheet id={id} x={176} y={45} angle={2} />
      <g transform="translate(246 79)">
        {[0, 1, 2].map((index) => (
          <g key={index} transform={`translate(${index * 9} ${index * 39})`}>
            <g className={styles.label}>
              <path d="M0 0H125Q131 0 131 6V24Q131 30 125 30H0L-14 15Z" fill={index === 1 ? "#ECF4DA" : "#F7FAFC"} stroke={index === 1 ? "#A9C875" : "#9EBFCE"} strokeWidth="1.5" />
              <circle cx="0" cy="15" r="3" fill="#8CB14C" />
              <path d="M13 11H71M13 19H56" stroke="#769DAE" strokeWidth="2.5" strokeLinecap="round" />
              <text x="103" y="19" textAnchor="middle" fontSize="10" fontWeight="700" fill="#285774" fontFamily="Arial, sans-serif">.PDF</text>
            </g>
          </g>
        ))}
      </g>
    </>
  );
}

function DistributionScene({ id }: { id: string }) {
  return (
    <>
      <path d="M219 137H258Q277 137 277 115V66H332M219 137H332M219 137H258Q277 137 277 159V207H332" stroke="#BCD2DC" strokeWidth="2" />
      <path className={styles.route} d="M219 137H258Q277 137 277 115V66H332M219 137H332M219 137H258Q277 137 277 159V207H332" stroke="#4394AD" strokeWidth="3" strokeLinecap="round" strokeDasharray="10 170" />
      <Sheet id={id} x={107} y={60} angle={-7} className={styles.lift} />
      <g transform="translate(141 104)">
        <circle cx="31" cy="31" r="28" fill="#EDF5DF" stroke="#BAD489" />
        <path d="M22 31H40M31 22V40" stroke="#668F2C" strokeWidth="2" strokeLinecap="round" />
      </g>
      {[0, 1, 2].map((index) => (
        <g key={index} transform={`translate(332 ${39 + index * 70})`}>
          <rect x="2" y="4" width="99" height="54" rx="9" fill="#DCE8EE" />
          <rect width="99" height="54" rx="9" fill={`url(#${id}-paper)`} stroke="#B2CBD7" strokeWidth="1.5" />
          <g transform="translate(8 7) scale(.78)"><Person x={0} y={0} blue /></g>
          <path d="M49 17H83M49 26H74" stroke="#87ABBC" strokeWidth="3" strokeLinecap="round" />
          <rect className={styles.destination} x="49" y="37" width="27" height="4" rx="2" fill="#A3CA4E" />
          <circle cx="-8" cy="27" r="4" fill="#F7FAFC" stroke="#5C9EB8" strokeWidth="2" />
        </g>
      ))}
    </>
  );
}
