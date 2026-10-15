import type { CompanyPeoplePage } from "../types/company-people";

/** Exhausted work is never presented as an active background refresh. */
export function companyIndexPending(page?: CompanyPeoplePage) {
  return Boolean(page?.indexing_pending && !page.indexing_failed);
}
