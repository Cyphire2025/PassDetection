import { useSyncExternalStore } from "react";

const subscribe = (listener: () => void) => {
  window.addEventListener("popstate", listener);
  return () => window.removeEventListener("popstate", listener);
};

/** The test router models native history notifications supplied by Next. */
export function useCompanyViewState() {
  const query = useSyncExternalStore(subscribe, () => window.location.search.slice(1));
  return { params: new URLSearchParams(query), query, update(changes: Record<string, string | undefined>) {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value); else next.delete(key);
    }
    window.history.replaceState(null, "", `${window.location.pathname}?${next}`);
    window.dispatchEvent(new PopStateEvent("popstate"));
  } };
}
