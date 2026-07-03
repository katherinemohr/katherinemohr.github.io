/* Study Guides offline service worker.
   - same-origin pages/guides: network-first (fresh when online, cached fallback offline)
   - Google Fonts (CSS + woff2): cache-first (immutable, so they work on a plane)
   The "Save all for offline" button on the library pre-fills this cache with every guide. */
const CACHE = "sg-offline-v3";
const FONT_HOSTS = ["fonts.googleapis.com", "fonts.gstatic.com"];

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (e) => e.waitUntil((async () => {
  const keys = await caches.keys();
  await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
  await self.clients.claim();
})()));

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);

  if (FONT_HOSTS.includes(url.hostname)) {           // fonts: cache-first
    e.respondWith((async () => {
      const c = await caches.open(CACHE);
      const hit = await c.match(req);
      if (hit) return hit;
      try { const res = await fetch(req); if (res && (res.ok || res.type === "opaque")) c.put(req, res.clone()); return res; }
      catch (err) { return hit || Response.error(); }
    })());
    return;
  }

  if (url.origin === location.origin) {              // our pages: network-first, fall back to cache
    e.respondWith((async () => {
      const c = await caches.open(CACHE);
      try {
        const res = await fetch(req);
        if (res && res.ok) c.put(req, res.clone());
        return res;
      } catch (err) {
        const hit = await c.match(req);
        return hit || await c.match("./") || new Response("Offline and not cached yet.", { status: 503, headers: { "Content-Type": "text/plain" } });
      }
    })());
  }
});
