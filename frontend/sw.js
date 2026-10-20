// Service Worker: App-Shell offline verfügbar, letzte Feed-Antworten (nur Text) als Offline-Fallback.
// Bilder fremder Server werden nicht angefasst und nicht gecacht.
const VERSION = "v3";
const SHELL_CACHE = `shell-${VERSION}`;
const API_CACHE = `api-${VERSION}`;
const SHELL = [
  "/", "/index.html", "/styles.css", "/app.js", "/manifest.webmanifest",
  "/icons/icon.svg", "/icons/icon-192.png", "/icons/icon-512.png",
  ...["top", "politik", "wirtschaft", "tech", "ki", "gaming", "sport", "wissenschaft", "kultur", "bestpreise", "regional"]
    .map((t) => `/icons/topics/${t}.svg`),
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => ![SHELL_CACHE, API_CACHE].includes(k)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;

  if (["/api/topics", "/api/feed", "/api/regions"].includes(url.pathname)) {
    event.respondWith(networkFirstApi(req, url));
  } else if (!url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirstShell(req));
  }
});

async function networkFirstApi(req, url) {
  const cache = await caches.open(API_CACHE);
  // Nur erste Seiten cachen (ohne Cursor), damit der Cache klein bleibt.
  const cacheable = !Number(url.searchParams.get("offset"));
  try {
    const res = await fetch(req);
    if (res.ok && cacheable) await cache.put(req, res.clone());
    return res;
  } catch (err) {
    const cached = cacheable && await cache.match(req);
    if (!cached) throw err;
    const headers = new Headers(cached.headers);
    headers.set("X-From-Cache", "1");
    return new Response(await cached.blob(), { status: 200, headers });
  }
}

// Network-first: nach einem Update kommt sofort die neue App; offline greift der Cache.
async function networkFirstShell(req) {
  const cache = await caches.open(SHELL_CACHE);
  try {
    const res = await fetch(req);
    if (res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const cached = await cache.match(req, { ignoreSearch: true })
      || (req.mode === "navigate" && await cache.match("/index.html"));
    if (cached) return cached;
    throw err;
  }
}
