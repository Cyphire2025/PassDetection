import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { fieldClass, WorkspaceSearch } from "./workspace-ui";
import type { RecipientRoster } from "./use-recipient-roster";

export function RecipientRosterFilters({ roster, group }: {
  roster: RecipientRoster;
  group: WhatsAppBroadcastGroupDetail
}) {
  const { search, setSearch, filter, setFilter, sort, setSort, setOffset, people, failedCount, notSentCount, sourceIssues } = roster;
  return <>
    <WorkspaceSearch
      value={search}
      onChange={(value) => {
        setSearch(value);
        setOffset(0);
      }}
      label="Search recipients"
      placeholder="Search name, number or imported details…"
    >
      <label className="text-xs text-slate-500">
        <span className="sr-only">Sort recipients</span>
        <select
          aria-label="Sort recipients"
          disabled={filter === "issues"}
          value={sort}
          onChange={(event) => {
            setSort(event.target.value);
            setOffset(0);
          }}
          className={`${fieldClass} w-auto`}
        >
          <option value="asc">Name A–Z</option>
          <option value="desc">Name Z–A</option>
          <option value="import">Import order</option>
        </select>
      </label>
    </WorkspaceSearch>
    <div className="flex flex-wrap gap-2">
      {[
        { id: "all", label: "All recipients", count: people.length },
        { id: "failed", label: "Welcome failed", count: failedCount },
        {
          id: "not_sent",
          label: "Welcome not sent",
          count: notSentCount,
        },
        {
          id: "issues",
          label: "Contact issues",
          count: group.rejected_contact_count + sourceIssues.length,
        },
      ].map((item) => (
        <button
          key={item.id}
          onClick={() => {
            setFilter(item.id);
            setOffset(0);
          }}
          aria-pressed={filter === item.id}
          aria-label={`${item.label} (${item.count})`}
          className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${filter === item.id ? "bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200" : "bg-slate-50 text-slate-600 hover:bg-slate-100"}`}
        >
          {item.label}
          <span className="ml-2 tabular-nums opacity-70">
            {item.count.toLocaleString()}
          </span>
        </button>
      ))}
    </div>
    {filter === "failed" && (
      <p className="text-xs leading-5 text-slate-500">
        These welcome sends failed. Correct a number here; Delivery
        history shows the recorded reason for each send.
      </p>
    )}
  </>;
}
