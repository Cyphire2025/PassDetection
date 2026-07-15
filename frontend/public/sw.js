const CACHE_NAME = "passdetection-tour-ops-v5";
const CORE_ASSETS = [
  "/coordinator",
  "/tour-scanner",
  "/tour-operations",
  "/tour-operations/group-assignments",
  "/manifest.webmanifest",
  "/pwa-icon.svg",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)).catch(() => undefined),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return;
  if (url.pathname.startsWith("/_next/static/")) return;
  if (url.pathname.startsWith("/_next/")) return;
  if (url.pathname === "/favicon.ico" || url.pathname.includes(".")) return;

  const isNavigation = event.request.mode === "navigate" || event.request.destination === "document";
  if (!isNavigation) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(() => caches.match(event.request).then((cached) => cached || caches.match("/coordinator"))),
  );
});
