"use client";

import { Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { aiSettingsApi, type AssistantConfiguration, type GrantPerson, type GrantRole } from "../settings-api";

const ROLES: { id: GrantRole; label: string }[] = [
  { id: "agency_admin", label: "Agency administrators" }, { id: "agency_manager", label: "Managers" }, { id: "agency_staff", label: "Staff" },
];

export function AssistantAccessSettings({ value, people: granted, onChange }: {
  value: AssistantConfiguration; people: GrantPerson[]; onChange: (configuration: AssistantConfiguration) => void;
}) {
  const [query, setQuery] = useState("");
  const [people, setPeople] = useState<GrantPerson[]>([]);
  const [knownPeople, setKnownPeople] = useState<Record<string, GrantPerson>>(() => Object.fromEntries(granted.map((person) => [person.id, person])));
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    const timer = setTimeout(() => { void aiSettingsApi.people(query, abort.signal).then((result) => {
      if (abort.signal.aborted) return;
      setPeople(result.items); setHasMore(result.has_more); setError("");
      setKnownPeople((current) => ({ ...current, ...Object.fromEntries(result.items.map((person) => [person.id, person])) }));
    }).catch(() => { if (!abort.signal.aborted) setError("Accounts could not be loaded. Try searching again."); }); }, 250);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [query]);
  const toggleRole = (role: GrantRole) => onChange({ ...value, allowed_roles: value.allowed_roles.includes(role) ? value.allowed_roles.filter((item) => item !== role) : [...value.allowed_roles, role] });
  const togglePerson = (id: string) => onChange({ ...value, allowed_user_ids: value.allowed_user_ids.includes(id) ? value.allowed_user_ids.filter((item) => item !== id) : [...value.allowed_user_ids, id] });
  return <section className="rounded-xl border border-slate-200 bg-white p-6">
    <h3 className="text-sm font-semibold text-slate-900">Who can use AI</h3>
    <p className="mt-2 text-sm leading-6 text-slate-500">Super administrators have access when AI is enabled. Everyone else needs a role or individual grant. Their existing agency and group permissions still apply.</p>
    <fieldset className="mt-5 space-y-3"><legend className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-500">Allow by role</legend>{ROLES.map((role) => <label key={role.id} className="flex cursor-pointer items-center gap-3 text-sm text-slate-700"><input type="checkbox" className="h-4 w-4 rounded accent-blue-600" checked={value.allowed_roles.includes(role.id)} onChange={() => toggleRole(role.id)} />{role.label}</label>)}</fieldset>
    <div className="mt-6 border-t border-slate-100 pt-5">
      <label htmlFor="assistant-account-search" className="text-xs font-semibold uppercase tracking-wide text-slate-500">Allow individual accounts</label>
      <div className="relative mt-3"><Search size={16} className="absolute left-3 top-3 text-slate-400" /><input id="assistant-account-search" type="search" autoComplete="off" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name or email" className="h-10 w-full rounded-lg border border-slate-200 bg-white pl-9 pr-3 text-sm outline-blue-500" /></div>
      {value.allowed_user_ids.length ? <div className="mt-3 flex flex-wrap gap-2" aria-label="Allowed individual accounts">{value.allowed_user_ids.map((id) => <span key={id} className="inline-flex items-center gap-2 rounded-full bg-blue-50 px-3 py-1.5 text-xs text-blue-800">{knownPeople[id]?.name || granted.find((person) => person.id === id)?.name || "Selected account"}<button type="button" aria-label={`Remove AI access for ${knownPeople[id]?.name || granted.find((person) => person.id === id)?.name || "selected account"}`} onClick={() => togglePerson(id)}><X size={13} /></button></span>)}</div> : null}
      <div className="mt-3 max-h-56 overflow-y-auto rounded-lg border border-slate-100">{people.map((person) => <label key={person.id} className="flex cursor-pointer items-center gap-3 border-b border-slate-100 px-3 py-3 last:border-b-0 hover:bg-slate-50"><input type="checkbox" className="h-4 w-4 shrink-0 accent-blue-600" checked={value.allowed_user_ids.includes(person.id)} disabled={!value.allowed_user_ids.includes(person.id) && value.allowed_user_ids.length >= 200} onChange={() => togglePerson(person.id)} /><span className="min-w-0"><span className="block text-sm font-medium text-slate-700">{person.name}</span><span className="block truncate text-xs text-slate-500">{person.email} · {person.role.replaceAll("agency_", "").replaceAll("_", " ")}</span></span></label>)}</div>
      {hasMore ? <p className="mt-2 text-xs text-slate-500">Showing the first 30 matches. Refine your search to find another account.</p> : null}
      {error ? <p className="mt-2 text-sm text-rose-700" role="alert">{error}</p> : null}
    </div>
  </section>;
}
