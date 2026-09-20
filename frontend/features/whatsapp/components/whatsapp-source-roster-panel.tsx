import Link from "next/link";
import type { Route } from "next";
import { Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import type { WhatsAppBroadcastSourceContacts } from "../api/whatsapp-source-groups.api";
import { ErrorBanner, readErrorMessage } from "./whatsapp-dialog-ui";
import { SourceContactTable } from "./whatsapp-source-contact-table";

export function SourceRosterPanel({ data, isLoading, isFetching, error, onRetry }: {
  data: WhatsAppBroadcastSourceContacts | undefined;
  isLoading: boolean;
  isFetching: boolean;
  error: unknown;
  onRetry: () => void;
}) {
  return (
    <section className="space-y-5 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6" aria-label="Source group travellers">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h3 className="font-semibold text-slate-900">Travellers</h3><p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-500">Every traveller from the source group is kept here, including people who share a WhatsApp number. Delivery numbers receive one message each per send.</p></div>
        <Button type="button" variant="secondary" onClick={onRetry} isLoading={isFetching}>Refresh travellers</Button>
      </div>
      {error ? <ErrorBanner message={readErrorMessage(error, "The source traveller list could not be loaded. Try refreshing it.")} />
        : isLoading || !data ? <Skeleton className="h-56" /> : <>
          <div className="grid grid-cols-3 gap-3 rounded-xl bg-slate-50 p-4">
            {[["Travellers", data.total_contacts], ["Delivery numbers", data.unique_phone_count], ["Need attention", data.needs_attention_count]].map(([label, count]) => <div key={label}><p className="text-xs text-slate-500">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums text-slate-900">{Number(count).toLocaleString()}</p></div>)}
          </div>
          <div className="flex flex-wrap gap-2">
            {data.sources.map((source) => <Link key={source.id} href={ROUTES.dashboard.passportGroup(source.id) as Route} className="rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-700 hover:border-blue-300 hover:text-blue-700">{source.name}{" "}{source.import_only && <span className="ml-2 inline-flex whitespace-nowrap rounded bg-slate-100 px-1.5 py-0.5 text-xs">Import only</span>}</Link>)}
          </div>
          {data.needs_attention_count > 0 && <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">{data.needs_attention_count} traveller {data.needs_attention_count === 1 ? "row needs" : "rows need"} attention. Review the contact status below before delivery. These rows stay visible here.</p>}
          {data.shared_phone_count > 0 && <p className="text-sm text-blue-700">{data.shared_phone_count} additional traveller{data.shared_phone_count === 1 ? " shares" : "s share"} an existing delivery number. Every name is retained.</p>}
          <SourceContactTable contacts={data.contacts} showGroup={data.sources.length > 1} />
        </>}
    </section>
  );
}
