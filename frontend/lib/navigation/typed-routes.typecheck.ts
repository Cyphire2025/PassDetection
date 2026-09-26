import type { Route } from "next";
import { ROUTES } from "@/constants/routes";

// Compiled by the normal type-check gate. Never executed at runtime.
export function checkGeneratedRouteContracts() {
  const acceptsRoute = <T extends string>(route: Route<T>) => route;
  acceptsRoute(ROUTES.dashboard.passportDetail("submission"));
  acceptsRoute(ROUTES.dashboard.documentDistributionFlightLane("group", "domestic", "return"));
  acceptsRoute(ROUTES.auth.coordinatorLogin("/coordinator"));
  // @ts-expect-error A misspelled page must remain rejected by generated Next types.
  acceptsRoute("/passprts");
  // @ts-expect-error Unknown nested routes must remain rejected too.
  acceptsRoute("/passports/groups/id/does-not-exist");
}
