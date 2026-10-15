/* OceanEye shared client: auth headers (dev mode), fetch wrapper, protected media as blob URLs,
   WebSocket with auto-reconnect, PWA install + offline state, Web Push subscription, formatting
   helpers and toasts. No build step, no framework. */
(function () {
  "use strict";

  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  const OE = {
    role: null, user: null, cameras: {}, config: null, beach: null,

    init(defaultRole, defaultUser) {
      const page = location.pathname.split("/").pop() || "index";
      this._page = page;
      this.role = store.get(`oe_role_${page}`, defaultRole);
      this.user = store.get(`oe_user_${page}`, defaultUser);
      this.registerServiceWorker();
      this.watchConnectivity();
      this.watchInstallPrompt();
    },
    setRole(r) { this.role = r; store.set(`oe_role_${this._page}`, r); },
    setUser(u) { this.user = u || "user"; store.set(`oe_user_${this._page}`, this.user); },
    headers(extra = {}) { return { "X-Dev-Role": this.role, "X-Dev-User": this.user, ...extra }; },

    /* ------------------------------------------------------------------ http */
    async api(path, opts = {}) {
      const init = { method: opts.method || "GET", headers: this.headers(opts.headers) };
      if (opts.json !== undefined) {
        init.body = JSON.stringify(opts.json);
        init.headers["Content-Type"] = "application/json";
      }
      if (opts.body) init.body = opts.body;
      const r = await fetch("/api" + path, init);
      if (r.status === 204) return null;
      const ct = r.headers.get("content-type") || "";
      const data = ct.includes("json") ? await r.json() : await r.text();
      if (!r.ok) {
        const msg = (data && data.error && data.error.message) || r.statusText;
        const err = new Error(msg); err.status = r.status; err.data = data; throw err;
      }
      return data;
    },

    _blobs: {},
    async cachedBlobUrl(url, key = url) { return this._blobs[key] || this.blobUrl(url, key); },
    async blobUrl(url, key = url) {   // protected media (needs headers) -> object URL
      const r = await fetch(url, { headers: this.headers() });
      if (!r.ok) throw new Error(r.status);
      const u = URL.createObjectURL(await r.blob());
      if (this._blobs[key]) URL.revokeObjectURL(this._blobs[key]);
      this._blobs[key] = u; return u;
    },

    /* ------------------------------------------------------------- websocket */
    connect(onMessage, onStatus, cameraIds) {
      if (this._ws) return;                       // one socket per page
      let delay = 1000;
      const open = () => {
        const q = new URLSearchParams({ dev_role: this.role, dev_user: this.user });
        (cameraIds || []).forEach((c) => q.append("camera_id", c));
        const scheme = location.protocol === "https:" ? "wss" : "ws";
        const ws = new WebSocket(`${scheme}://${location.host}/ws/alerts?${q}`);
        this._ws = ws;
        ws.onopen = () => { delay = 1000; onStatus && onStatus(true); };
        ws.onmessage = (e) => { try { onMessage(JSON.parse(e.data)); } catch (err) { console.error(err); } };
        ws.onclose = () => {
          this._ws = null;
          onStatus && onStatus(false);
          setTimeout(open, delay);
          delay = Math.min(delay * 2, 15000);
        };
      };
      open();
      // One keepalive for the page, not one per connect() call.
      if (!this._ping) {
        this._ping = setInterval(() => {
          if (this._ws && this._ws.readyState === 1) this._ws.send('{"action":"ping"}');
        }, 25000);
      }
    },

    /* ------------------------------------------------------------ app state */
    async loadConfig() {
      this.config = await this.api("/config/public");
      this.beach = this.config.beach;
      return this.config;
    },
    async loadCameras(beachId) {
      const q = beachId ? `?beach_id=${encodeURIComponent(beachId)}` : "";
      const list = await this.api("/cameras" + q);
      this.cameras = Object.fromEntries(list.map((c) => [c.id, c]));
      return list;
    },
    camName(id) { return (this.cameras[id] && this.cameras[id].name) || id; },

    /* -------------------------------------------------------- PWA behaviour */
    registerServiceWorker() {
      if (!("serviceWorker" in navigator)) return;
      // Service workers need a secure origin. Over plain http on a LAN address the browser refuses,
      // which is expected - the page still works, just without install or background alerts.
      if (!window.isSecureContext) return;
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((err) => {
        console.warn("service worker not registered:", err.message);
      });
    },

    watchConnectivity() {
      const paint = () => document.body.classList.toggle("is-offline", !navigator.onLine);
      window.addEventListener("online", paint);
      window.addEventListener("offline", paint);
      document.addEventListener("DOMContentLoaded", paint);
      paint();
    },

    /** Capture the install prompt so a page can offer "Add to home screen" at a sensible moment. */
    watchInstallPrompt() {
      window.addEventListener("beforeinstallprompt", (e) => {
        e.preventDefault();
        this._installEvent = e;
        document.dispatchEvent(new CustomEvent("oe-installable"));
      });
      window.addEventListener("appinstalled", () => { this._installEvent = null; });
    },
    get installable() { return Boolean(this._installEvent); },
    async promptInstall() {
      if (!this._installEvent) return null;
      this._installEvent.prompt();
      const { outcome } = await this._installEvent.userChoice;
      this._installEvent = null;
      return outcome;
    },
    get installed() {
      return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
    },

    /* --------------------------------------------------------- web push */
    /** Why a subscription could not be made - used to tell the user something actionable. */
    pushBlockedReason() {
      if (!window.isSecureContext) {
        return "Background alerts need a secure (https) connection. Open the https address, "
             + "or keep this page open for sound and vibration alerts.";
      }
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
        return "This browser does not support background alerts.";
      }
      if (!(this.config && this.config.capabilities && this.config.capabilities.web_push)) {
        return "Background alerts are not switched on for this server.";
      }
      if ("Notification" in window && Notification.permission === "denied") {
        return "Notifications are blocked for this site. Allow them in the browser's site settings.";
      }
      return null;
    },

    /** Subscribe this browser for background alerts. Returns {ok, reason}. */
    /** `cameraIds` is the guard's post: which cameras they cover. An empty list means roaming,
     *  and a roaming device receives every alert - never fewer. */
    async enablePush(label, cameraIds = []) {
      const blocked = this.pushBlockedReason();
      if (blocked) return { ok: false, reason: blocked };
      try {
        const permission = await Notification.requestPermission();
        if (permission !== "granted") return { ok: false, reason: "Notification permission was not granted." };
        const reg = await navigator.serviceWorker.ready;
        const { public_key: key } = await this.api("/push/public-key");
        const existing = await reg.pushManager.getSubscription();
        const sub = existing || await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(key),
        });
        const body = sub.toJSON();
        await this.api("/push/subscribe", {
          method: "POST",
          json: { endpoint: body.endpoint, keys: body.keys, label: label || this.user,
                  assigned_camera_ids: cameraIds },
        });
        return { ok: true };
      } catch (err) {
        return { ok: false, reason: err.message || String(err) };
      }
    },

    async disablePush() {
      try {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (!sub) return;
        const body = sub.toJSON();
        await this.api("/push/unsubscribe", { method: "POST", json: { endpoint: body.endpoint, keys: body.keys } });
        await sub.unsubscribe();
      } catch (err) { console.warn("could not unsubscribe:", err.message); }
    },

    /* --------------------------------------------------------- formatting */
    ago(iso) {
      if (!iso) return "–";
      // Clamped at zero: a phone whose clock runs a few seconds behind the server would otherwise
      // report an incident as "-8s ago", which reads as a bug at exactly the wrong moment.
      const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
      if (s < 60) return `${s}s ago`;
      if (s < 3600) return `${Math.floor(s / 60)}m ago`;
      if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
      return new Date(iso).toLocaleString();
    },
    pct(x) { return x == null ? "–" : `${Math.round(x * 100)}%`; },
    num(x, d = 1, unit = "") { return x == null ? "–" : `${Number(x).toFixed(d)}${unit}`; },
    secs(x) { return x == null ? "–" : x < 90 ? `${x.toFixed(0)}s` : `${(x / 60).toFixed(1)}m`; },
    signal(s) { return s.replace(/_/g, " "); },
    esc(s) {
      return String(s ?? "").replace(/[&<>"']/g, (c) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    },

    toast(msg, kind = "") {
      let box = document.getElementById("toasts");
      if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
      const t = document.createElement("div");
      t.className = `toast ${kind}`;
      t.textContent = msg;
      box.appendChild(t);
      setTimeout(() => t.remove(), kind === "alert" ? 9000 : 5000);
    },

    beep(times = 2, freq = 880) {     // works after one user gesture (browser autoplay rules)
      try {
        this._ac = this._ac || new (window.AudioContext || window.webkitAudioContext)();
        const ac = this._ac;
        if (ac.state === "suspended") ac.resume();
        for (let i = 0; i < times; i++) {
          const o = ac.createOscillator(), g = ac.createGain();
          o.frequency.value = freq; o.type = "square"; g.gain.value = 0.08;
          o.connect(g); g.connect(ac.destination);
          const t0 = ac.currentTime + i * 0.35; o.start(t0); o.stop(t0 + 0.2);
        }
      } catch { /* audio unavailable */ }
    },

    weather(code) {
      const m = {
        0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Fog",
        51: "Drizzle", 53: "Drizzle", 55: "Drizzle", 61: "Rain", 63: "Rain", 65: "Heavy rain",
        80: "Showers", 81: "Showers", 82: "Violent showers", 95: "Thunderstorm", 96: "Thunderstorm",
        99: "Thunderstorm",
      };
      return code == null ? "–" : (m[code] || `code ${code}`);
    },

    /** `roles` is a list of wire values, or [value, label] pairs where the label is what the
     *  operator reads. The wire value is always the Role the API expects. */
    roleSelect(el, roles) {
      el.innerHTML = roles.map((r) => {
        const [value, label] = Array.isArray(r) ? r : [r, r];
        return `<option value="${value}" ${value === this.role ? "selected" : ""}>${label}</option>`;
      }).join("");
      el.onchange = () => { this.setRole(el.value); location.reload(); };
    },
  };

  /** VAPID keys travel as base64url; PushManager wants raw bytes. */
  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  window.OE = OE;
})();
