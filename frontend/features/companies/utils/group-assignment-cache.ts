import type { QueryClient } from "@tanstack/react-query";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { useAuthStore } from "@/stores/auth.store";
import { companyKeys } from "../hooks/use-companies";

/** Replace only existing bounded list entries; never create an unscoped cache. */
export async function refreshGroupAssignment(client: QueryClient, saved: UploadLinkResponse, sessionVersion: number) {
  await client.cancelQueries({ queryKey: ["upload-links", "list"] });
  if (useAuthStore.getState().sessionVersion !== sessionVersion) throw new Error("Your session changed. Reopen the group before continuing.");
  client.setQueriesData<UploadLinkResponse[]>({ queryKey: ["upload-links", "list"] },
    (groups) => groups?.map((group) => group.id === saved.id && group.agency_id === saved.agency_id ? saved : group));
  await Promise.all([
    client.invalidateQueries({ queryKey: ["upload-links"] }),
    client.invalidateQueries({ queryKey: ["passports", "groups"] }),
    client.invalidateQueries({ queryKey: ["document-distribution", "groups"] }),
    client.invalidateQueries({ queryKey: companyKeys.scope(saved.agency_id) }),
    client.invalidateQueries({ queryKey: ["gc-app", saved.agency_id] }),
  ]);
}
