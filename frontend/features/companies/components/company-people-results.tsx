import type { CompanyPeoplePage } from "../types/company-people";
import { companyIndexPending } from "../utils/company-index-status";
import { CompanyError, CompanyLoading } from "./company-feedback";
import { CompanyPersonRow } from "./company-person-row";

export function CompanyPeopleResults({ data, loading, error, retry, companyId, query, search, hint }: {
  data?: CompanyPeoplePage; loading: boolean; error: boolean; retry: () => void;
  companyId: string; query: string; search: string; hint?: string;
}) {
  if (loading) return <CompanyLoading />;
  if (hint) return <p role="status" className="px-4 py-6 text-sm text-slate-500">{hint}</p>;
  if (error) return <CompanyError message="People could not be loaded." retry={retry} />;
  return <>
    {data?.indexing_failed && <p role="status" className="border-b border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-900">Some records could not be added to this list. Your saved records are safe. Refresh to check again, or contact support if this continues.</p>}
    {data?.items.length ? <ul className="divide-y divide-slate-100">{data.items.map((person) => <CompanyPersonRow key={person.id} person={person} companyId={companyId} query={query} />)}</ul> : <p className="px-4 py-8 text-sm text-slate-500">{companyIndexPending(data) ? "Saved records are being indexed. Refresh to check for updates." : search ? "No matching people. Try another name or traveller ID." : "No people in this view."}</p>}
  </>;
}
