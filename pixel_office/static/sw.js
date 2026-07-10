// Pixel Office service worker — offline shell + last-snapshot for phone monitoring.
// Local-first caveat: the app is only reachable from a phone once promoted via
// the deploy playbook (tunnel). This SW makes the shell installable and keeps the
// LAST seen state visible offline; it never implies the local office is remotely
// reachable on its own.
const CACHE = "pixel-office-v1";
const SHELL = ["/", "/icon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/ws")) return;
  // network-first for live data; fall back to cache (stale) when offline
  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        if (resp.ok && (url.pathname === "/" || SHELL.includes(url.pathname))) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return resp;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/")))
  );
});
