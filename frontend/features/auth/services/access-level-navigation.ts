import type { User } from "@/types";
import { firstAuthorizedPath } from "../config/route-capabilities";

export function navigateToAccessLevel(user: User) {
  // A new document discards component state, prefetched routes, and active
  // connections that may have been created with a different access level.
  window.location.replace(firstAuthorizedPath(user));
}
