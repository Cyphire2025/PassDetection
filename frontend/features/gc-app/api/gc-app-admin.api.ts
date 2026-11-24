import { gcAppDirectoryApi } from "./gc-app-directory.api";
import { gcAppManagersApi } from "./gc-app-managers.api";
import { gcAppGroupsApi } from "./gc-app-groups.api";
import { gcAppDocumentsApi } from "./gc-app-documents.api";
import { gcAppItinerariesApi } from "./gc-app-itineraries.api";
import { gcAppAnnouncementsApi } from "./gc-app-announcements.api";
import { gcAppAuditApi } from "./gc-app-audit.api";

/** Stable dashboard facade; each endpoint family owns its original transport contract. */
export const gcAppAdminApi = {
  ...gcAppDirectoryApi,
  ...gcAppManagersApi,
  ...gcAppGroupsApi,
  ...gcAppDocumentsApi,
  ...gcAppItinerariesApi,
  ...gcAppAnnouncementsApi,
  ...gcAppAuditApi,
};

export { PAGE_SIZE as GC_APP_DEFAULT_PAGE_SIZE } from "./gc-app-transport";
