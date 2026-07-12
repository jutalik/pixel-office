// Pixel Office service worker — caches the app SHELL for offline/installable use.
// It caches the shell only; the LAST-seen office state is restored separately by the
// client from localStorage (`po:last`), not by this worker. Local-first caveat: the
// app is only reachable from a phone once promoted via a tunnel — this SW never
// implies the local office is remotely reachable on its own.
const CACHE = "pixel-office-v3";
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
  const isNav = e.request.mode === "navigate";
  const isShell = url.pathname === "/" || SHELL.includes(url.pathname);
  // network-first; on failure only the app SHELL falls back to cached HTML.
  // API/data GETs (e.g. /api/*) must FAIL explicitly — never serve HTML to a
  // JSON fetch (that would surface as a silent parse error in the app).
  e.respondWith(
    fetch(e.request)
      .then((resp) => {
        if (resp.ok && isShell) {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return resp;
      })
      .catch(async () => {
        const cached = await caches.match(e.request);
        if (cached) return cached;
        if (isNav) return (await caches.match("/")) || Response.error();
        return Response.error();   // let the app's own fetch().catch handle it
      })
  );
});
