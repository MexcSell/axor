/* AXoR's service worker: shows the Web Push notifications AXoR Push delivers, even with no AXoR tab open, and opens
   AXoR where a notification points when it's clicked. It handles push and notification events only: no caching and
   no fetch handler. Registered from /static/, so it controls no pages; it reaches open tabs through postMessage. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

const windows = () => self.clients.matchAll({ type: "window", includeUncontrolled: true });
async function tell(msg) { (await windows()).forEach(c => c.postMessage(msg)); }

self.addEventListener("push", e => {
  let m;
  try { m = e.data ? e.data.json() : {}; } catch { m = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(m.title || "AXoR", {
    body: m.body || "", icon: "/static/brand/icon-192.png", tag: m.tag || "", renotify: !!m.tag,
    timestamp: m.ts ? m.ts * 1000 : Date.now(), data: { url: m.url || "/#notifications" },
  }).then(() => tell({ type: "push", message: m })));  // open tabs refresh their bell
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = new URL(e.notification.data?.url || "/#notifications", self.location.origin);
  e.waitUntil((async () => {
    if (url.origin !== self.location.origin) return self.clients.openWindow(url.href);
    const tab = (await windows()).find(c => new URL(c.url).pathname === "/");
    if (!tab) return self.clients.openWindow(url.href);
    await tab.focus();
    tab.postMessage({ type: "open", url: url.hash || "#notifications" });
  })());
});

// the browser replaced the subscription (expiry, key rotation): register the new one for whoever is signed in here
self.addEventListener("pushsubscriptionchange", e => {
  e.waitUntil((async () => {
    const key = e.oldSubscription?.options?.applicationServerKey;
    const sub = e.newSubscription || (key && await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }));
    if (!sub) return;
    const { endpoint, keys } = sub.toJSON();
    await fetch("/api/push/devices", { method: "PUT", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Requested-With": "scout" },
      body: JSON.stringify({ endpoint, p256dh: keys.p256dh, auth: keys.auth }) });
  })());
});
