"use client";

import { useDeferredValue, useMemo, useState } from "react";
import { clampPageOffset } from "@/lib/utils/pagination";
import type { WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { useWhatsAppBroadcastSourceContacts } from "../hooks/use-whatsapp-source-groups";
import { recipientPeople, recipientWelcomeSummary, openRecipientDetails } from "./recipient-roster-model";

export function useRecipientRoster(group: WhatsAppBroadcastGroupDetail) {
  const [search, setSearch] = useState("");
  const deferred = useDeferredValue(search).trim().toLocaleLowerCase();
  const [filter, setFilter] = useState("all");
  const [sort, setSort] = useState("asc");
  const [offset, setOffset] = useState(0);
  const [openDetails, setOpenDetails] = useState<string[]>([]);
  const sources = useWhatsAppBroadcastSourceContacts(
    group.id,
    Boolean(group.source_contact_count || group.has_import_only_source),
  );
  const people = useMemo(
    () => recipientPeople(group.recipients, sources.data?.contacts),
    [group.recipients, sources.data?.contacts],
  );
  const welcome = useMemo(() => recipientWelcomeSummary(people), [people]);
  const { failedCount, notSentCount } = welcome;
  const sourceIssues =
    sources.data?.contacts.filter((contact) => !contact.recipient_id) ?? [];
  const displayed = useMemo(() => {
    const result = people.filter(
      (person) =>
        (filter !== "failed" || welcome.statuses.get(person) === "failed") &&
        (filter !== "not_sent" || welcome.statuses.get(person) === "not_sent") &&
        (!deferred ||
          [
            person.name,
            person.recipient.normalized_phone_number,
            ...Object.values(person.fields),
          ].some((value) => value.toLocaleLowerCase().includes(deferred))),
    );
    return sort === "import"
      ? result
      : result.sort(
        (a, b) =>
          a.name.localeCompare(b.name, "en", {
            sensitivity: "base",
            numeric: true,
          }) * (sort === "desc" ? -1 : 1),
      );
  }, [people, welcome, filter, deferred, sort]);
  const pageOffset = clampPageOffset(offset, displayed.length, 50);
  const details = useMemo(() => openRecipientDetails(people, openDetails), [people, openDetails]);
  return {
    search,
    setSearch,
    deferred,
    filter,
    setFilter,
    sort,
    setSort,
    setOffset,
    openDetails,
    setOpenDetails,
    sources,
    sourceIssues,
    people,
    failedCount,
    notSentCount,
    displayed,
    pageOffset,
    details
  };
}

export type RecipientRoster = ReturnType<typeof useRecipientRoster>;
