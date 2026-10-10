/* OceanEye service worker.
 *
 * Three jobs:
 *   1. Make both interfaces installable - the control room on a PC, the lifeguard app on a phone.
 *   2. Keep the app shell usable when the Wi-Fi drops - a lifeguard should see the last screen and a
 *      clear "offline" banner, not a browser error page.
 *   3. Receive Web Push messages and raise the OS notification, so an alert reaches a phone whose
 *      screen is off and whose browser is closed. This is the only part of OceanEye that runs when
 *      nothing else is running, so it is deliberately tiny and dependency-free.
 *
 * Caching rule: the shell (HTML, CSS, JS, icons) is cache-first; everything under /api/ and every
 * WebSocket is network-only. Operational data must never be served stale - a cached incident list
 * would be a safety defect, not a convenience.
 *
 * Served from the site root with Service-Worker-Allowed: / so one worker covers /ui/*.
 */

const VERSION = "oceaneye-v4";
const SHELL = `${VERSION}-shell`;
const OFFLINE_URL = "/offline.html";

const SHELL_URLS = [
  OFFLINE_URL,
  "/ui/",
  "/ui/index.html",
  "/ui/control.html",
  "/ui/lifeguard.html",
  "/ui/css/oceaneye.css",
  "/ui/js/api.js",
  "/ui/js/control.js",
  "/ui/js/lifeguard.js",
  "/ui/icons/icon-192.png",
  "/ui/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL)
      // addAll fails the whole install if any single URL 404s; add individually so one missing
      // optional file cannot leave the app without a service worker at all.
      .then((cache) => Promise.all(SHELL_URLS.map((url) => cache.add(url).catch(() => null))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

function isApiRequest(url) {
  return url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")
    || url.pathname === "/health" || url.pathname === "/ready";
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;   // fonts, map tiles: leave to the network
  if (isApiRequest(url)) return;                      // never serve operational data from a cache

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(SHELL).then((cache) => cache.put(request, copy)).catch(() => {});
          return response;
        })
        .catch(() => caches.match(request).then((hit) => hit || caches.match(OFFLINE_URL))),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((hit) => {
      if (hit) {
        // Refresh in the background so a republished page is picked up on the next load.
        fetch(request).then((fresh) => {
          if (fresh && fresh.ok) caches.open(SHELL).then((c) => c.put(request, fresh)).catch(() => {});
        }).catch(() => {});
        return hit;
      }
      return fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(SHELL).then((cache) => cache.put(request, copy)).catch(() => {});
        }
        return response;
      });
    }),
  );
});

/* ---------------------------------------------------------------- push */

const LEVEL_LABEL = { critical: "CRITICAL", high: "HIGH", medium: "MEDIUM", low: "LOW" };

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (err) {
    data = {};
  }
  // A connection check from the control room must never look or sound like a swimmer in trouble:
  // no alarm vibration, no sticky notification, and the open app is told so it can say "received".
  if (data.test) {
    event.waitUntil((async () => {
      const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      clients.forEach((c) => c.postMessage({ type: "push-test" }));
      await self.registration.showNotification("OceanEye test alert", {
        body: "Connection check from the control room. This phone is reachable. Not an incident.",
        icon: "/ui/icons/icon-192.png",
        badge: "/ui/icons/icon-192.png",
        tag: "oceaneye-test",
        silent: true,
        data: { url: "/ui/lifeguard.html" },
      });
    })());
    return;
  }

  const level = LEVEL_LABEL[data.risk_level] || "";
  const where = [data.camera, data.zone].filter(Boolean).join(" · ");
  const signals = (data.signals || []).map((s) => s.replace(/_/g, " ")).join(", ");
  const body = [where, level && `${level} risk`, signals].filter(Boolean).join("\n");

  event.waitUntil(
    self.registration.showNotification(data.title || "OceanEye alert", {
      body: body || "Open OceanEye to see the incident.",
      icon: "/ui/icons/icon-192.png",
      badge: "/ui/icons/icon-192.png",
      // One notification per event: a replaced notification is better than a stack of duplicates.
      tag: data.event_id || "oceaneye-alert",
      renotify: true,
      requireInteraction: true,          // stays on screen until the lifeguard acts
      vibrate: [300, 150, 300, 150, 300],
      data: { event_id: data.event_id, url: "/ui/lifeguard.html" },
      actions: [{ action: "open", title: "Open" }],
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/ui/lifeguard.html";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      // Reuse an already-open lifeguard window rather than stacking tabs during an incident.
      for (const client of clients) {
        if (client.url.includes("lifeguard") && "focus" in client) {
          client.postMessage({ type: "push-opened", event_id: event.notification.data?.event_id });
          return client.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting();
});
