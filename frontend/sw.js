// Tylko strona offline, API nie cache'ujemy (dane muszą być świeże).
// nowa wersja strony offline (0.12.5: po angielsku, 0.12.6: bez nazw źródeł danych, 0.13.0: Arial bez pogrubień):
// stara pamięć jest usuwana w activate
// 0.13.7: z czcionką (strona offline i aplikacja bez sieci w tej samej czcionce)
const CACHE = "offline-v5";
const OFFLINE = "/static/offline.html";
const FONTS = ["/static/fonts/AtkinsonHyperlegibleNext-Regular-latin.woff2",
  "/static/fonts/AtkinsonHyperlegibleNext-Regular-latin-ext.woff2"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE, ...FONTS])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  if (FONTS.includes(new URL(e.request.url).pathname)) {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request)));
    return;
  }
  if (e.request.mode !== "navigate") return;
  e.respondWith(fetch(e.request).catch(() => caches.match(OFFLINE)));
});
