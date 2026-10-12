/* APORTIL scanner service worker: lets the scan page open with no network. API calls are never cached. */
const CACHE = "aportil-scan-{{ version }}";
const SHELL = {{ shell|safe }};
const PAGE = "/ticketing/scan/";

self.addEventListener("install", (event) => {
	event.waitUntil(
		caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null)))).then(() => self.skipWaiting())
	);
});

self.addEventListener("activate", (event) => {
	event.waitUntil(
		caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())
	);
});

self.addEventListener("fetch", (event) => {
	const req = event.request;
	const url = new URL(req.url);
	if (req.method !== "GET" || url.origin !== location.origin) return;
	if (url.pathname.startsWith(PAGE + "api/")) return; // network only

	if (req.mode === "navigate" && url.pathname === PAGE) {
		// network first; never cache a login redirect as if it were the scan page
		event.respondWith(
			fetch(req).then((res) => {
				if (res.ok && !res.redirected) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(PAGE, copy)); }
				return res;
			}).catch(() => caches.match(PAGE).then((r) => r || Response.error()))
		);
		return;
	}
	if (url.pathname.startsWith("/static/")) {
		event.respondWith(
			caches.match(req).then((hit) => hit || fetch(req).then((res) => {
				if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
				return res;
			}))
		);
	}
});
