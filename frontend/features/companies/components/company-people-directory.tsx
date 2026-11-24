import type { CompanyDirectoryState } from "../hooks/use-company-directory-state";
import { CompanyPagination } from "./company-feedback";
import { CompanyPeopleToolbar } from "./company-people-toolbar";
import { CompanyPeopleResults } from "./company-people-results";

export function CompanyPeopleDirectory({ companyId, state }: {
  companyId: string;
  state: CompanyDirectoryState;
}) {
  const { view, search, cursor, sort, submissions, term, settled, searchHint, people, ready } = state;
  return (
    <section
      aria-label="Company people"
      aria-busy={!settled || people.isFetching}
      className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
    >
      <CompanyPeopleToolbar
        search={search}
        sort={sort}
        submissions={submissions}
        pending={people.isFetching}
        disabled={!ready || people.isFetching || Boolean(searchHint)}
        onSearch={(value) => view.update({ peopleSearch: value, peopleCursor: undefined })}
        onSort={(value) => view.update({ peopleSort: value, peopleCursor: undefined })}
        onSubmissions={(value) => view.update({ submissions: value, peopleCursor: undefined })}
        refresh={() => void people.refetch()}
      />
      <CompanyPeopleResults
        data={people.data}
        loading={!ready || people.isLoading}
        error={people.isError}
        retry={() => void people.refetch()}
        companyId={companyId}
        query={view.query}
        search={term}
        hint={searchHint}
      />
      <div className="border-t border-slate-100 px-4 py-2 text-xs text-slate-500">Up to 100 people per page</div>
      {(cursor || people.data?.has_more) && <CompanyPagination
        cursor={cursor}
        hasMore={!people.isError && Boolean(people.data?.has_more)}
        nextCursor={people.data?.next_cursor ?? null}
        pending={!ready || !settled || people.isFetching}
        onChange={(value) => view.update({ peopleCursor: value })}
      />}
    </section>
  );
}
