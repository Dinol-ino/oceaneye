/* The lifeguard app: the whole phone-side module.
 *
 * Alerting is layered on purpose, because each layer fails in a different way:
 *   1. WebSocket + in-page alarm - instant, but only while the app is open and awake.
 *   2. Web Push + service worker - reaches a closed app and a dark screen, but needs https.
 *   3. A repeating alarm while anything is unacknowledged - the backstop if a phone was put down.
 * The options panel lets a lifeguard turn each layer off deliberately, and says plainly which ones
 * are actually active, so nobody relies on protection they do not have.
 *
 * Preferences are kept on the phone (localStorage), not on the server: they describe this handset
 * in this lifeguard's pocket, and a phone with no network must still honour them.
 */
"use strict";

OE.init("lifeguard", "lifeguard");
const $ = (id) => document.getElementById(id);

const OPTS = { sound: "optSound", vibrate: "optVibrate", repeat: "optRepeat", push: "optPush" };
const PREF_KEY = "oe_alert_opts";

let armed = false;          // has the lifeguard tapped once? browsers need that before any sound
let alarmTimer = null;
let ACTIVE = [];
let pushState = { ok: false, reason: "Background alerts not requested yet." };

/* ---------------------------------------------------------------- options */

function readPrefs() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(PREF_KEY) || "{}"); } catch { saved = {}; }
  Object.entries(OPTS).forEach(([key, id]) => {
    if (typeof saved[key] === "boolean") $(id).checked = saved[key];
  });
}

function prefs() {
  return Object.fromEntries(Object.entries(OPTS).map(([key, id]) => [key, $(id).checked]));
}

function savePrefs() {
  try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs())); } catch { /* private mode */ }
}

/** What is actually protecting this lifeguard right now, one indicator per layer. */
function renderLayers() {
  const p = prefs();
  const line = (ok, text) => `<span class="pill"><span class="dot ${ok ? "on" : "off"}"></span>${text}</span>`;
  $("layers").innerHTML = [
    line(armed && p.sound, "alarm sound"),
    line(armed && p.vibrate && Boolean(navigator.vibrate), "vibration"),
    line(p.push && pushState.ok, "background alerts"),
  ].join(" ")
    + (p.push && !pushState.ok
      ? `<div class="small" style="margin-top:6px">${OE.esc(pushState.reason)}</div>` : "");
}

Object.values(OPTS).forEach((id) => ($(id).onchange = async () => {
  savePrefs();
  if (id === OPTS.push) {
    if ($(id).checked) {
      pushState = await OE.enablePush($("who").value.trim() || OE.user);
      if (!pushState.ok) OE.toast(pushState.reason, "err");
    } else {
      await OE.disablePush();
      pushState = { ok: false, reason: "Background alerts turned off on this phone." };
      OE.toast("Background alerts off — this phone only alerts while the app is open");
    }
  }
  updateAlarm();
  renderLayers();
}));

$("optTest").onclick = () => {
  armed = true;                       // the tap itself is the gesture browsers require
  ring(true);
  OE.toast("That is what an alert sounds like.");
  renderLayers();
};

/* ---------------------------------------------------------------- setup */

$("who").value = OE.user === "lifeguard" ? "" : OE.user;
$("who").onchange = () => OE.setUser($("who").value.trim().slice(0, 60) || "lifeguard");

$("enable").onclick = async () => {
  // A user gesture is required before a browser will play audio or ask for notifications.
  armed = true;
  ring(true);

  const notes = ["Alarm sound on."];
  if (prefs().push) {
    pushState = await OE.enablePush($("who").value.trim() || OE.user);
    notes.push(pushState.ok
      ? "Background alerts on — this phone will ring even with the app closed."
      : `${pushState.reason} Keep this page open and the screen on.`);
  } else {
    pushState = { ok: false, reason: "Background alerts turned off on this phone." };
    notes.push("Background alerts are switched off in Alert options.");
  }
  $("perm").textContent = notes.join(" ");
  $("enable").textContent = "Alerts on";
  $("enable").className = "lg-enable ok";
  $("enable").disabled = true;
  $("alertOpts").open = true;
  updateAlarm();
  renderLayers();
  showInstallHint();
};

/* -------------------------------------------------------- install prompt */

function showAppbar(text, actionLabel, onAction) {
  $("appbarText").textContent = text;
  const action = $("appbarAction");
  action.textContent = actionLabel;
  action.onclick = async () => { await onAction(); $("appbar").classList.remove("show"); };
  $("appbarDismiss").onclick = () => $("appbar").classList.remove("show");
  $("appbar").classList.add("show");
}

function showInstallHint() {
  if (OE.installed) return;
  if (OE.installable) {
    showAppbar("Add OceanEye Lifeguard to your home screen so it opens like an app.",
               "Install", () => OE.promptInstall());
  } else if (/iphone|ipad|ipod/i.test(navigator.userAgent)) {
    showAppbar("On iPhone: tap Share, then 'Add to Home Screen'.", "Got it", () => {});
  }
}
document.addEventListener("oe-installable", showInstallHint);

/* ---------------------------------------------------------------- alarm */

function ring(single = false) {
  const p = prefs();
  if (p.sound) OE.beep(single ? 2 : 3, 990);
  if (p.vibrate && navigator.vibrate) navigator.vibrate(single ? [200, 100, 200] : [300, 150, 300]);
}

function updateAlarm() {
  const p = prefs();
  const pending = ACTIVE.some((a) => ["pending", "escalated"].includes(a.payload.event_status));
  const shouldRing = pending && armed && (p.sound || p.vibrate);
  if (shouldRing && !alarmTimer) {
    ring();
    // "Keep repeating" off means one alarm per alert, not a silent phone: the first ring always
    // happens, only the repetition is optional.
    alarmTimer = p.repeat ? setInterval(ring, 2500) : setTimeout(() => { alarmTimer = null; }, 2500);
  } else if (!shouldRing && alarmTimer) {
    clearInterval(alarmTimer);
    clearTimeout(alarmTimer);
    alarmTimer = null;
  }
}

/* ---------------------------------------------------------------- data */

async function refresh() {
  try {
    await OE.loadCameras();
    const alerts = await OE.api("/alerts?active_only=true&limit=20");
    // Unacknowledged first, then by risk: the one needing a decision is always at the top.
    ACTIVE = alerts.sort((a, b) => {
      const urgency = (x) => (x.payload.event_status === "pending" ? 0 : 1);
      return urgency(a) - urgency(b) || b.payload.risk_score - a.payload.risk_score;
    });
  } catch (e) {
    $("alerts").innerHTML = `<div class="empty">${OE.esc(e.message)}</div>`;
    return;
  }
  render();
  updateAlarm();
}

function render() {
  const box = $("alerts");
  if (!ACTIVE.length) {
    box.innerHTML = '<div class="empty">No active alerts. You will hear an alarm when one arrives.</div>';
    return;
  }
  box.innerHTML = ACTIVE.map(card).join("");
  box.querySelectorAll("[data-ack]").forEach((b) => (b.onclick = () => ack(b.dataset.ack)));
  box.querySelectorAll("[data-out]").forEach((b) => (b.onclick = () => outcome(b.dataset.id, b.dataset.out)));
  ACTIVE.forEach(async (a) => {
    const img = box.querySelector(`[data-thumb="${a.payload.event_id}"]`);
    if (!img) return;
    if (!a.payload.thumbnail_url) { img.remove(); return; }
    try { img.src = await OE.cachedBlobUrl(a.payload.thumbnail_url, "t_" + a.payload.event_id); }
    catch { img.remove(); }
  });
}

function card(a) {
  const p = a.payload;
  const st = p.event_status;
  const lvl = p.risk_level || "high";
  const demo = (p.reason || "").startsWith("DEMO");
  const left = st === "pending" ? Math.max(0, Math.round((new Date(p.ack_deadline) - Date.now()) / 1000)) : null;
  const nav = `https://www.google.com/maps/dir/?api=1&destination=${p.location.lat},${p.location.lon}`;
  const banner = st === "pending" ? "POSSIBLE DISTRESS" : st === "escalated" ? "ESCALATED" : "RESPONDING";
  const signals = p.distress_signals.map((s) => `<span class="chip">${OE.signal(s)}</span>`).join(" ")
    || '<span class="small">no behaviour signals listed</span>';

  return `<div class="lg-alert ${st}" style="margin-bottom:14px">
    <div class="banner"><span>${banner}</span><span>${OE.pct(p.risk_score)}</span></div>
    <img data-thumb="${p.event_id}" alt="Evidence frame from ${OE.esc(OE.camName(p.camera_id))}">
    <div class="content">
      <div><b style="font-size:18px">${OE.esc(OE.camName(p.camera_id))}</b>
        ${p.location.zone_name ? ` · ${OE.esc(p.location.zone_name)}` : ""}</div>
      <div class="small">${OE.ago(p.timestamp)} · level
        <span class="lvl ${lvl}">${lvl.toUpperCase()}</span>${
          left != null ? ` · escalates in <b>${left}s</b>` : ""}${
          p.escalation_level ? ` · escalation tier ${p.escalation_level}` : ""}${
          demo ? ' · <span class="chip demo">DEMO</span>' : ""}</div>
      <div>${signals}</div>
      <div class="big">
        ${st !== "acknowledged"
          ? `<button class="danger" data-ack="${p.event_id}">ACKNOWLEDGE</button>`
          : `<button class="ok" data-out="resolved" data-id="${p.event_id}">Rescued / resolved</button>`}
        <a class="btn" href="${nav}" target="_blank" rel="noopener">Navigate</a>
      </div>
      ${st === "acknowledged"
        ? `<div class="big"><button class="ghost" data-out="false_alarm" data-id="${p.event_id}">False alarm</button><span></span></div>`
        : ""}
    </div></div>`;
}

async function ack(id) {
  try {
    await OE.api(`/events/${id}/ack`, { method: "POST", json: { note: "responding" } });
    OE.toast("Acknowledged — control room notified");
  } catch (e) { OE.toast(e.message, "err"); }
  refresh();
}

async function outcome(id, out) {
  try {
    await OE.api(`/events/${id}/outcome`, { method: "POST", json: { outcome: out } });
    OE.toast(out === "resolved" ? "Marked resolved" : "Marked false alarm — this is how the system learns");
  } catch (e) { OE.toast(e.message, "err"); }
  refresh();
}

/* ---------------------------------------------------------------- live */

OE.connect(
  (msg) => {
    if (!msg.type || !msg.type.startsWith("alert.")) return;
    // The control room's connection check: confirm it arrived, do not alarm, do not refetch.
    if (msg.payload && msg.payload.event_id === "test") {
      OE.toast("Test alert from the control room — this phone is reachable.");
      return;
    }
    refresh();
  },
  (on) => {
    $("wsdot").className = `dot ${on ? "on" : "off"}`;
    $("wstext").textContent = on ? "on duty · live" : "reconnecting…";
  },
);

// Tapping a background notification focuses this window; refresh so the alert is on screen.
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("message", (e) => {
    if (!e.data) return;
    if (e.data.type === "push-test") {
      OE.toast("Test alert from the control room — this phone is reachable.");
      return;
    }
    if (e.data.type === "push-opened") refresh();
  });
}

(async function start() {
  readPrefs();
  try {
    const cfg = await OE.loadConfig();
    $("sitePill").textContent = cfg.beach ? cfg.beach.name : cfg.location_name;
    $("emergency").textContent = cfg.emergency_phone || "112";
    const blocked = OE.pushBlockedReason();
    if (blocked) pushState = { ok: false, reason: blocked };
  } catch { /* the alert list still works */ }
  renderLayers();
  refresh();
  setInterval(refresh, 5000);
  setInterval(render, 1000);   // keeps the escalation countdown ticking
  showInstallHint();
})();
