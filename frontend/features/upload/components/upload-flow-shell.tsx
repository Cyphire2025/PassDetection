import type { ReactNode } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";
import { BrandLogo } from "@/components/brand/brand-logo";
import { isValidPassportIsoDate } from "@/lib/utils/passport-date";

const travelDateFormatter = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
});

export function UploadHeader({ groupName, departureDate, returnDate }: {
  groupName: string;
  departureDate?: string | null;
  returnDate?: string | null;
}) {
  const travelDates = [
    { label: "Departure Date", value: departureDate?.trim() },
    { label: "Return Date", value: returnDate?.trim() },
  ].flatMap(({ label, value }) => value && isValidPassportIsoDate(value)
    ? [{ label, value, display: travelDateFormatter.format(new Date(`${value}T00:00:00Z`)) }]
    : []);
  return (
    <div className="mb-5 text-center sm:mb-8 lg:mb-10">
      <BrandLogo
        className="mx-auto mb-4 h-16 w-[240px] sm:mb-6 sm:h-20 sm:w-[300px]"
        priority
      />
      <h1 className="mb-2 text-2xl font-extrabold tracking-tight text-slate-900 sm:mb-3 sm:text-3xl">Upload Travel Documents</h1>
      <p className="mx-auto max-w-md text-sm leading-relaxed text-slate-500 sm:text-base">
        Global Connect Travels has requested passport details for
      </p>
      <div className="mt-2 inline-flex max-w-full rounded-full bg-blue-50 px-3 py-1 font-semibold text-blue-600">
        <span className="truncate">{groupName}</span>
      </div>
      {travelDates.length > 0 && (
        <dl className="mx-auto mt-3 flex flex-wrap justify-center gap-x-8 gap-y-2 text-sm">
          {travelDates.map(({ label, value, display }) => (
            <div key={label}>
              <dt className="text-xs font-medium text-slate-500">{label}</dt>
              <dd className="mt-0.5 font-semibold text-slate-800"><time dateTime={value}>{display}</time></dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

export function ChoiceCard({
  icon,
  title,
  description,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="group flex w-full items-start gap-3 rounded-2xl border-2 border-slate-100 bg-white p-4 text-left shadow-sm transition-all active:scale-[0.99] hover:border-blue-600 hover:bg-blue-50/50 hover:shadow-md sm:gap-4 sm:p-5"
    >
      <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-blue-600 transition-colors group-hover:bg-blue-600 group-hover:text-white sm:h-12 sm:w-12">
        {icon}
      </div>
      <div className="min-w-0">
        <h4 className="text-base font-bold text-slate-900 transition-colors group-hover:text-blue-900">
          {title}
        </h4>
        <p className="mt-1 text-sm leading-5 text-slate-500">{description}</p>
      </div>
    </button>
  );
}

export function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mb-4 inline-flex items-center gap-2 text-sm font-medium text-slate-600"
    >
      <ArrowLeft className="h-4 w-4" />
      Back
    </button>
  );
}

export function ErrorMessage({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      aria-live="assertive"
      className="mb-5 rounded-xl border border-red-100 bg-red-50 p-4 text-sm font-medium text-red-700"
    >
      {message}
    </div>
  );
}

export function CenteredLoader() {
  return (
    <CenteredShell>
      <div role="status" aria-live="polite">
        <Loader2 className="h-8 w-8 animate-spin text-blue-600" aria-hidden="true" />
        <span className="sr-only">Loading secure upload</span>
      </div>
    </CenteredShell>
  );
}

export function CenteredShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-4">
      {children}
    </div>
  );
}

export function ProcessingScreen({
  title,
  description,
  progress,
}: {
  title: string;
  description: string;
  progress?: number | null;
}) {
  const progressPercent = typeof progress === "number"
    ? Math.max(0, Math.min(100, Math.round(progress * 100)))
    : null;

  return (
    <CenteredShell>
      <div
        aria-busy="true"
        className="flex w-full max-w-md flex-col items-center justify-center text-center"
      >
        <div className="relative mb-8">
          <div className="absolute inset-0 animate-pulse rounded-full bg-blue-500/20 blur-xl" />
          <div className="relative flex h-24 w-24 items-center justify-center rounded-full bg-blue-600 shadow-xl shadow-blue-600/20">
            <Loader2 className="h-10 w-10 animate-spin text-white" aria-hidden="true" />
          </div>
        </div>
        <div role="status" aria-live="polite" aria-atomic="true">
          <h2 className="mb-2 text-2xl font-bold tracking-tight text-slate-900">{title}</h2>
          <p className="mx-auto max-w-xs text-slate-500">{description}</p>
        </div>
        {progressPercent !== null && (
          <div
            role="progressbar"
            aria-label="Passport processing progress"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={progressPercent}
            className="mt-6 h-2 w-full max-w-xs overflow-hidden rounded-full bg-slate-200"
          >
            <div
              className="h-full rounded-full bg-blue-600 transition-all duration-500"
              style={{ width: `${Math.max(8, progressPercent)}%` }}
            />
          </div>
        )}
      </div>
    </CenteredShell>
  );
}
