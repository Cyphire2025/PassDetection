const CACHE_NAME = "passdetection-public-static-v8";
const PUBLIC_STATIC_ASSETS = [
  "/offline.html",
  "/offline-scanner.js",
  "/offline/vendor/zxing-browser.min.js",
];
const PUBLIC_STATIC_PATHS = new Set(PUBLIC_STATIC_ASSETS);
const COORDINATOR_PATH_PATTERN = /^\/coordinator(?:\/|$)/;

function cacheOfflineShell() {
  return caches.open(CACHE_NAME).then((cache) => cache.addAll(PUBLIC_STATIC_ASSETS));
}

function warmOfflineShell() {
  return cacheOfflineShell().catch(() => undefined);
}

function removeRetiredAppCaches() {
  return caches.keys().then((keys) =>
    Promise.all(
      keys
        .filter((key) => key.startsWith("passdetection-") && key !== CACHE_NAME)
        .map((key) => caches.delete(key)),
    ),
  );
}

function rewarmAfterSuccessfulCoordinatorResponse(event, responsePromise) {
  event.waitUntil(
    responsePromise
      .then((response) => (response.ok ? warmOfflineShell() : undefined))
      .catch(() => undefined),
  );
}

self.addEventListener("install", (event) => {
  // A partial offline runtime is not safe to activate. Let installation fail
  // so the previous complete worker remains in control.
  event.waitUntil(cacheOfflineShell());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(removeRetiredAppCaches());
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  if (event.request.mode === "navigate") {
    const networkResponse = fetch(event.request);

    // Logout intentionally clears every application cache. A later successful
    // coordinator navigation re-warms only this public static allowlist so the
    // cold-offline scanner is restored without caching navigation, API, Next,
    // image, font, stylesheet, or user-data responses.
    if (COORDINATOR_PATH_PATTERN.test(url.pathname)) {
      rewarmAfterSuccessfulCoordinatorResponse(event, networkResponse);
    }

    event.respondWith(
      networkResponse
        .then(async (response) => {
          if (
            COORDINATOR_PATH_PATTERN.test(url.pathname)
            && response.status >= 500
          ) {
            return (await caches.match("/offline.html")) ?? response;
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match("/offline.html");
          return cached ?? new Response("You are offline.", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" },
          });
        }),
    );
    return;
  }

  // Next client-side route changes use a same-origin fetch rather than a new
  // document navigation. Observe that response without caching it so the first
  // successful coordinator visit after logout can still restore the shell.
  if (
    COORDINATOR_PATH_PATTERN.test(url.pathname)
    && event.request.destination === ""
  ) {
    const coordinatorResponse = fetch(event.request);
    rewarmAfterSuccessfulCoordinatorResponse(event, coordinatorResponse);
    event.respondWith(coordinatorResponse);
    return;
  }

  if (PUBLIC_STATIC_PATHS.has(url.pathname)) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached ?? fetch(event.request)),
    );
  }
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
    return;
  }

  if (event.data?.type === "CLEAR_SENSITIVE_CACHES") {
    // The current cache contains only the exact public offline shell allowlist.
    // The page-side logout cleanup may remove it too; the next successful
    // coordinator navigation safely restores it via warmOfflineShell().
    event.waitUntil(removeRetiredAppCaches());
  }
});
