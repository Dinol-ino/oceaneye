/* The control room: the whole PC-side module.
 *
 * OceanEye has two interfaces, matching the two people who use it:
 *   - this one, on a PC in the control room: the deployment site, the camera wall, the danger-zone
 *     editor, incidents, the map, sea and weather, recorded-footage analysis, response metrics, and
 *     the panel that proves alerts reach the phones;
 *   - the lifeguard app on a phone: an alert, the evidence, and one Acknowledge button.
 *
 * Video analysis lives here rather than in a page of its own because it is the same job - watching
 * this beach's footage - done against a recording instead of a live stream, and because the person
 * testing a camera is the person who configured it.
 */
"use strict";

OE.init("operator", "control-room");
// Two roles, not three. OceanEye runs for ONE beach: the person who configures the site is the
// person who watches it, so splitting "operator" and "administrator" only produced a dialog that
// failed with "Insufficient permissions" and no way to tell which half you were. The wire value
// stays `operator` so stored principals and the Role enum are unchanged.
OE.roleSelect(document.getElementById("role"), [["operator", "controller"], ["lifeguard", "lifeguard"]]);

const $ = (id) => document.getElementById(id);
const ACTIVE_STATUSES = ["pending", "acknowledged", "escalated"];

let CFG = null;
let BEACH = null;
let LIVE = {};
let ALERTS = {};
let EVENTS = {};
let UPLOADS = [];
let FOUND = [];          // the current place-search results, indexed by the buttons rendered for them
let DEVICES = [];
let map = null;
const layers = {};
let editingCam = null;
let zonePts = [];
let zoneBg = null;

function closeModal(id) {
  $(id).classList.remove("open");
  if (id === "clipModal") $("clipVideo").pause();
  if (id === "vidModal") $("vid").pause();
}
window.closeModal = closeModal;
setInterval(() => ($("clock").textContent = new Date().toLocaleTimeString()), 1000);

/* ------------------------------------------------------- install prompt */

document.addEventListener("oe-installable", () => {
  if (OE.installed) return;
  $("appbarText").textContent = "Install the Control Room as an app on this device.";
  $("appbarAction").onclick = async () => { await OE.promptInstall(); $("appbar").classList.remove("show"); };
  $("appbarDismiss").onclick = () => $("appbar").classList.remove("show");
  $("appbar").classList.add("show");
});

/* ======================================================= deployment site ==
   One installation watches one beach. Everything else - cameras, incidents, weather, the map
   centre - is read off it, so this is the first thing to configure and the only thing that must be
   configured before the system is useful. */

function renderSite() {
  if (!BEACH) {
    $("siteInfo").innerHTML = '<span class="small">No beach configured yet — choose one.</span>';
    $("sitePill").textContent = "no beach set";
    return;
  }
  $("sitePill").textContent = BEACH.name;
  // A beach stored at 0,0 is a record with no coordinates, not a beach in the Atlantic. Everything
  // positional reads off these numbers - the map centre, the weather lookup, new camera markers -
  // so say so here rather than letting it surface later as a blank map.
  const unplaced = BEACH.lat === 0 && BEACH.lon === 0;
  const coords = unplaced
    ? '<div class="small warn-text">No coordinates on this site — the map, weather and camera '
      + 'placement cannot work until it is re-picked. Use “Change beach”.</div>'
    : `<div class="small mono">${BEACH.lat.toFixed(5)}, ${BEACH.lon.toFixed(5)}</div>`;
  $("siteInfo").innerHTML = `
    <div>
      <div class="name">${OE.esc(BEACH.name)}</div>
      <div class="small">${OE.esc(BEACH.region || "area not recorded")}</div>
      ${coords}
    </div>
    <dl>
      <dt>Authority</dt><dd>${OE.esc(BEACH.authority_name || "not set")}</dd>
      <dt>Contact</dt><dd>${OE.esc(BEACH.authority_phone || "not set")}</dd>
      <dt>Lifeguards on duty</dt><dd>${BEACH.lifeguard_count}</dd>
      <dt>Cameras</dt><dd>${BEACH.camera_count}</dd>
    </dl>`;
}

$("siteBtn").onclick = async () => {
  if (BEACH) {
    $("sAuthority").value = BEACH.authority_name || "";
    $("sPhone").value = BEACH.authority_phone || "";
    $("sGuards").value = BEACH.lifeguard_count;
    $("sRegionText").value = BEACH.region || "";
  }
  await loadConfiguredSites();
  if (!(CFG.capabilities || {}).place_search) {
    $("sResults").innerHTML = '<div class="small">Place search is not configured on this server '
      + '(set <span class="mono">OCEANEYE_GEOAPIFY_API_KEY</span>). Add the beach by hand below.</div>';
    $("sManualWrap").open = true;
  } else {
    $("sResults").innerHTML = '<div class="small">Type a place name and press Search.</div>';
  }
  $("siteModal").classList.add("open");
  $("sQuery").focus();
};

async function loadConfiguredSites() {
  const sites = await OE.api("/beaches").catch(() => []);
  $("sConfigured").innerHTML = sites.map((s) => `
    <div class="row ${s.is_active ? "active" : ""}">
      <div><b>${OE.esc(s.name)}</b>
        <div class="small">${OE.esc(s.region || "—")} · ${s.camera_count} camera(s)
          · ${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}</div></div>
      ${s.is_active
        ? '<span class="chip">this deployment</span>'
        : `<button class="ghost" data-activate="${s.id}">Watch this beach</button>`}
    </div>`).join("") || '<div class="small">None yet.</div>';
  $("sConfigured").querySelectorAll("[data-activate]").forEach((b) => (b.onclick = async () => {
    try {
      await OE.api(`/beaches/${b.dataset.activate}/activate`, { method: "POST" });
      OE.toast("Deployment beach changed — reloading");
      setTimeout(() => location.reload(), 700);
    } catch (e) {
      // "Insufficient permissions" alone leaves the operator with no idea what to do. Changing
      // which beach an installation watches redefines the deployment, so it is administrator-only
      // (see app/environment/api/router.py) - say that, and name the control that fixes it.
      OE.toast(e.status === 403
        ? "Changing the deployment beach is administrator-only — switch the role selector at the "
          + "top right to administrator and try again."
        : e.message, "err");
    }
  }));
}

/** One search box. The server answers with results plus, when there are none, the reason - which is
 *  the difference between "no such beach" and "this machine has no internet". */
async function runPlaceSearch(path, busy) {
  $("sResults").innerHTML = `<div class="small">${busy}</div>`;
  let body;
  try {
    body = await OE.api(path);
  } catch (e) {
    $("sResults").innerHTML = `<div class="small">${OE.esc(e.message)}</div>`;
    return;
  }
  FOUND = body.results;
  if (!FOUND.length) {
    const why = body.error ? OE.esc(body.error)
      : "Nothing matched. Try the town or district instead of the beach name.";
    $("sResults").innerHTML = `<div class="small">${why}</div>`;
    if (!body.available) $("sManualWrap").open = true;
    return;
  }
  $("sResults").innerHTML = FOUND.map((p, i) => `
    <div class="row">
      <div>
        <b>${OE.esc(p.name)}</b>
        <div class="small">${OE.esc(p.address)}</div>
        <div class="small mono">${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}${
          p.distance_km != null ? ` · ${p.distance_km} km away` : ""}</div>
      </div>
      <button data-pick="${i}">Watch this beach</button>
    </div>`).join("");
  $("sResults").querySelectorAll("[data-pick]")
    .forEach((btn) => (btn.onclick = () => pickPlace(FOUND[btn.dataset.pick])));
}

/** Picking a place during setup means "this is the beach we watch" - there is no other reason to
 *  pick one, so it is applied immediately rather than stored as a candidate. */
async function pickPlace(p) {
  try {
    await OE.api("/beaches", {
      method: "POST",
      json: { name: p.name, region: p.address || "", lat: p.lat, lon: p.lon,
              source_id: p.source_id, activate: true },
    });
    OE.toast(`${p.name} is now this installation's beach — reloading`);
    setTimeout(() => location.reload(), 800);
  } catch (e) { OE.toast(e.message, "err"); }
}

function searchCentre() {
  if (map) { const c = map.getCenter(); return [c.lat, c.lng]; }
  if (BEACH) return [BEACH.lat, BEACH.lon];
  return [CFG.lat, CFG.lon];
}

$("sGo").onclick = () => {
  const q = $("sQuery").value.trim();
  if (q.length < 2) return OE.toast("Type at least two characters", "err");
  const [lat, lon] = searchCentre();
  runPlaceSearch(`/places/search?q=${encodeURIComponent(q)}&lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}`,
                 "Searching…");
};
$("sQuery").onkeydown = (e) => { if (e.key === "Enter") $("sGo").click(); };
$("sNearby").onclick = () => {
  const [lat, lon] = searchCentre();
  runPlaceSearch(`/places/beaches-near?lat=${lat.toFixed(4)}&lon=${lon.toFixed(4)}&radius_km=25`,
                 "Looking for beaches within 25 km…");
};

$("sAdd").onclick = async () => {
  const name = $("sName").value.trim();
  const lat = Number($("sLat").value);
  const lon = Number($("sLon").value);
  if (!name) return OE.toast("Give the beach a name", "err");
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || !$("sLat").value || !$("sLon").value) {
    return OE.toast("Latitude and longitude are required", "err");
  }
  try {
    await OE.api("/beaches", {
      method: "POST",
      json: { name, region: $("sRegionText").value.trim(), lat, lon, activate: true },
    });
    OE.toast("Site added — reloading");
    setTimeout(() => location.reload(), 800);
  } catch (e) { OE.toast(e.message, "err"); }
};

/** Empty the search box and results. Separate from closing the dialog: an operator who mistyped a
 *  place wants the box cleared, not the whole setup flow restarted. */
$("sClear").onclick = () => {
  $("sQuery").value = "";
  FOUND = [];
  $("sResults").innerHTML = '<div class="small">Type a place name and press Search.</div>';
  $("sQuery").focus();
};

$("sManualClear").onclick = () => {
  ["sName", "sRegionText", "sLat", "sLon"].forEach((id) => ($(id).value = ""));
  $("sName").focus();
};

/** Revert, not clear: blanking these fields and saving would wipe the authority's real contact
 *  details, which is the opposite of what "clear the form" should ever do. */
$("sAuthRevert").onclick = () => {
  $("sAuthority").value = (BEACH && BEACH.authority_name) || "";
  $("sPhone").value = (BEACH && BEACH.authority_phone) || "";
  $("sGuards").value = (BEACH && BEACH.lifeguard_count) || 0;
  OE.toast("Showing the saved details");
};

$("sSaveAuthority").onclick = async () => {
  if (!BEACH) return OE.toast("Choose a beach first", "err");
  try {
    BEACH = await OE.api(`/beaches/${BEACH.id}`, {
      method: "PATCH",
      json: {
        authority_name: $("sAuthority").value.trim(),
        authority_phone: $("sPhone").value.trim(),
        lifeguard_count: Number($("sGuards").value || 0),
      },
    });
    renderSite();
    OE.toast("Authority details saved");
  } catch (e) { OE.toast(e.message, "err"); }
};

/* ============================================================== cameras == */

async function refreshCameras() {
  const [cams, live] = await Promise.all([
    OE.loadCameras(BEACH ? BEACH.id : undefined),
    OE.api("/live/cameras"),
  ]);
  LIVE = Object.fromEntries(live.map((l) => [l.camera_id, l]));
  const box = $("cams");
  if (!cams.length) return;

  const known = new Set([...box.querySelectorAll(".cam")].map((e) => e.dataset.id));
  if (cams.length !== known.size || cams.some((c) => !known.has(c.id))) {
    box.innerHTML = cams.map((c) => `
      <div class="cam" data-id="${c.id}">
        <div class="view"><img alt="Live view of ${OE.esc(c.name)}">
          <span class="badge pill"></span><span class="risk"></span><span class="msg"></span></div>
        <div class="meta">
          <div class="row"><span class="title">${OE.esc(c.name)}</span>
            <span class="small">${c.source_type.replace("_", " ")}</span></div>
          <div class="row small stats"></div>
          <div class="btns">
            <button class="mon"></button>
            <button class="ghost zone">Zone</button>
            <button class="ghost demo" title="Inject a clearly labelled DEMO alert to rehearse the response">Demo alert</button>
          </div>
        </div>
      </div>`).join("");
    box.querySelectorAll(".cam").forEach((el) => {
      const id = el.dataset.id;
      el.querySelector(".mon").onclick = () => toggleMonitor(id);
      el.querySelector(".zone").onclick = () => openZone(id);
      el.querySelector(".demo").onclick = async () => {
        try {
          await OE.api("/demo/incident", { method: "POST", json: { camera_id: id } });
          OE.toast("Demo alert sent");
        } catch (e) { OE.toast(e.message, "err"); }
      };
    });
  }

  box.querySelectorAll(".cam").forEach((el) => {
    const l = LIVE[el.dataset.id] || {};
    const st = l.stats || {};
    const state = l.online ? "online"
      : l.worker_state === "starting" ? "starting"
      : l.worker_state === "error" ? "error" : "offline";
    el.querySelector(".badge").innerHTML =
      `<span class="dot ${l.online ? "on" : state === "starting" ? "mid" : "off"}"></span>${state}`;
    const top = (st.risks || [])[0];
    el.querySelector(".risk").innerHTML = top
      ? `<span class="pill lvl ${top.level}">${top.level.toUpperCase()} ${OE.pct(top.score)}</span>` : "";
    el.querySelector(".stats").textContent = l.online
      ? `${st.people ?? 0} people · ${st.fps ?? "–"} fps · ${st.pipeline_ms ?? "–"} ms/frame`
        + ` · ${st.model || ""} ${st.device || ""} · events ${st.events ?? 0}`
        + (st.reconnects ? ` · ${st.reconnects} reconnect(s)` : "")
      : (l.worker_message || (l.monitoring ? "starting worker (loading model)…" : "not monitoring"));
    const btn = el.querySelector(".mon");
    btn.textContent = l.monitoring ? "Stop" : "Start monitoring";
    btn.className = l.monitoring ? "mon danger" : "mon ok";
    el.querySelector(".msg").textContent = l.online ? "" : (l.monitoring ? "Loading model…" : "Camera idle");
    if (!l.online) el.querySelector("img").removeAttribute("src");
  });
}

async function refreshFrames() {
  const live = [...document.querySelectorAll(".cam")]
    .filter((el) => LIVE[el.dataset.id] && LIVE[el.dataset.id].online);
  // Fetch the wall in parallel: serially, a six-camera wall updated once every six seconds.
  await Promise.all(live.map(async (el) => {
    const id = el.dataset.id;
    try { el.querySelector("img").src = await OE.blobUrl(`/api/live/cameras/${id}/frame`, `frame_${id}`); }
    catch { /* try again next tick */ }
  }));
}

async function toggleMonitor(id) {
  const on = LIVE[id] && LIVE[id].monitoring;
  try {
    await OE.api(`/cameras/${id}/monitoring/${on ? "stop" : "start"}`, { method: "POST" });
    OE.toast(on ? "Monitoring stopped" : "Worker starting — the first frame appears once the model loads");
  } catch (e) { OE.toast(e.message, "err"); }
  refreshCameras();
}

/* ----------------------------------------------------------- add camera */

$("addCamBtn").onclick = async () => {
  $("cLat").value = $("cLat").value || (BEACH ? BEACH.lat : CFG.lat);
  $("cLon").value = $("cLon").value || (BEACH ? BEACH.lon : CFG.lon);
  try {
    const ups = await OE.api("/uploads");
    $("cUpload").innerHTML = ups.length
      ? ups.map((u) => `<option value="${u.id}">${OE.esc(u.filename)}</option>`).join("")
      : "<option value=''>no uploads yet</option>";
  } catch (e) { $("cUpload").innerHTML = `<option value=''>${OE.esc(e.message)}</option>`; }
  $("camModal").classList.add("open");
};

$("cSrc").onchange = () => {
  const up = $("cSrc").value === "upload";
  $("cUpWrap").style.display = up ? "" : "none";
  $("cUrlWrap").style.display = up ? "none" : "";
};

$("cSave").onclick = async () => {
  const body = { name: $("cName").value, lat: +$("cLat").value, lon: +$("cLon").value };
  if (BEACH) body.beach_id = BEACH.id;
  if ($("cSrc").value === "upload") {
    // An uploaded clip is a FILE, and the worker decides whether to loop from source_type. Leaving
    // it at the schema default (rtsp) stored a camera that pointed at a local path but was treated
    // as a network stream, so it never opened and the camera sat "offline" with no explanation.
    if (!$("cUpload").value) return OE.toast("Upload a video first, or choose a stream URL", "err");
    body.video_upload_id = $("cUpload").value;
    body.source_type = "video_file";
  } else {
    if (!$("cUrl").value.trim()) return OE.toast("Enter the stream URL", "err");
    body.stream_url = $("cUrl").value.trim();
    body.source_type = "rtsp";
  }
  if (!body.name.trim()) return OE.toast("Give the camera a name", "err");
  try {
    await OE.api("/cameras", { method: "POST", json: body });
    closeModal("camModal");
    OE.toast("Camera created — draw its danger zone, then start monitoring");
    await refreshCameras();
    drawMap(); loadAnalysisCameras();
  } catch (e) { OE.toast(e.message, "err"); }
};

/* ---------------------------------------------------------- zone editor */

const zc = $("zCanvas");
const zx = zc.getContext("2d");

async function openZone(id) {
  editingCam = id; zonePts = []; zoneBg = null;
  $("zCam").textContent = OE.camName(id);
  try {
    const z = await OE.api(`/zones/${id}`);
    zonePts = z.polygon.map((p) => [p[0], p[1]]);
    $("zName").value = z.name;
  } catch { /* no zone yet */ }
  if (LIVE[id] && LIVE[id].online) {
    const img = new Image();
    img.onload = () => { zoneBg = img; zc.height = Math.round(zc.width * img.height / img.width); drawZone(); };
    img.src = await OE.blobUrl(`/api/live/cameras/${id}/frame`, "zonebg");
  }
  drawZone();
  $("zoneModal").classList.add("open");
}

function drawZone() {
  zx.fillStyle = "#16150f";
  zx.fillRect(0, 0, zc.width, zc.height);
  if (zoneBg) zx.drawImage(zoneBg, 0, 0, zc.width, zc.height);
  else {
    zx.fillStyle = "#a8a49a";
    zx.font = "16px Georgia, serif";
    zx.fillText("No live image — start monitoring to see the camera view", 20, 30);
  }
  if (!zonePts.length) return;
  zx.beginPath();
  zonePts.forEach(([x, y], i) => (i ? zx.lineTo(x * zc.width, y * zc.height) : zx.moveTo(x * zc.width, y * zc.height)));
  zx.closePath();
  zx.fillStyle = "rgba(179,34,28,0.28)";
  zx.fill();
  zx.strokeStyle = "#b3221c";
  zx.lineWidth = 3;
  zx.stroke();
  zonePts.forEach(([x, y]) => {
    zx.fillStyle = "#fff";
    zx.fillRect(x * zc.width - 4, y * zc.height - 4, 8, 8);
    zx.strokeStyle = "#16150f"; zx.lineWidth = 1;
    zx.strokeRect(x * zc.width - 4, y * zc.height - 4, 8, 8);
  });
}

zc.onclick = (e) => {
  const r = zc.getBoundingClientRect();
  zonePts.push([
    +((e.clientX - r.left) / r.width).toFixed(4),
    +((e.clientY - r.top) / r.height).toFixed(4),
  ]);
  drawZone();
};
$("zUndo").onclick = () => { zonePts.pop(); drawZone(); };
$("zClear").onclick = () => { zonePts = []; drawZone(); };
$("zHalf").onclick = () => { zonePts = [[0, 0.5], [1, 0.5], [1, 1], [0, 1]]; drawZone(); };
$("zSave").onclick = async () => {
  if (zonePts.length < 3) return OE.toast("A zone needs at least 3 points", "err");
  try {
    await OE.api(`/zones/${editingCam}`, { method: "PUT", json: { name: $("zName").value, polygon: zonePts } });
    OE.toast("Zone saved — restart monitoring so the worker picks it up");
    closeModal("zoneModal");
  } catch (e) { OE.toast(e.message, "err"); }
};

/* ============================================================ incidents == */

async function refreshIncidents() {
  const [events, alerts] = await Promise.all([
    OE.api("/events?limit=100"),
    OE.api("/alerts?active_only=true&limit=100"),
  ]);
  ALERTS = Object.fromEntries(alerts.map((a) => [a.event_id, a]));
  const active = events.filter((e) => ACTIVE_STATUSES.includes(e.status));
  $("incCount").textContent = `${active.length} active`;

  const box = $("incidents");
  box.innerHTML = active.length ? active.map(incidentCard).join("") : '<div class="empty">No active incidents.</div>';
  active.forEach(async (e) => {
    const el = box.querySelector(`[data-ev="${e.id}"] .thumb`);
    if (!e.evidence_thumbnail_url || !el) return;
    try {
      el.innerHTML = `<img src="${await OE.cachedBlobUrl(e.evidence_thumbnail_url, "t_" + e.id)}"
                           alt="Evidence frame" title="Play the evidence clip">`;
      el.querySelector("img").onclick = () => playClip(e);
    } catch { el.textContent = "no image"; }
  });
  box.querySelectorAll("[data-act]").forEach((b) => (b.onclick = () => act(b.dataset.id, b.dataset.act)));
  drawIncidentMarkers(active);
  renderHistory(events);
}

function incidentCard(e) {
  const lvl = e.risk_level || "medium";
  const a = ALERTS[e.id];
  const left = a && e.status === "pending"
    ? Math.max(0, Math.round((new Date(a.ack_deadline) - Date.now()) / 1000)) : null;
  const demo = (e.reason || "").startsWith("DEMO");
  return `<div class="inc ${lvl}" data-ev="${e.id}"><div class="bar"></div>
    <div class="thumb">no image</div>
    <div class="body">
      <div class="hd">
        <span class="status ${e.status}">${e.status.replace("_", " ")}</span>
        <b>${OE.esc(OE.camName(e.camera_id))}</b>
        <span class="lvl ${lvl}">${lvl.toUpperCase()} ${OE.pct(e.risk_score)}</span>
        ${demo ? '<span class="chip demo">DEMO</span>' : ""}
        <span class="small">${OE.ago(e.created_at)}${left != null ? ` · ack in <b>${left}s</b>` : ""}${
          e.escalation_level ? ` · escalated ×${e.escalation_level}` : ""}</span>
      </div>
      <div>${e.distress_signals.map((s) => `<span class="chip">${OE.signal(s)}</span>`).join(" ")}
        <span class="small">track ${OE.esc(e.track_id)} ${OE.esc(e.location.zone_name || "")}</span></div>
      <div class="reason" title="${OE.esc(e.reason)}">${OE.esc(e.reason || "")}</div>
      <div class="btns">
        ${e.status !== "acknowledged" ? `<button data-act="ack" data-id="${e.id}">Acknowledge</button>` : ""}
        ${e.status !== "escalated" ? `<button class="warn" data-act="escalate" data-id="${e.id}">Escalate</button>` : ""}
        <button class="ok" data-act="resolved" data-id="${e.id}">Resolved</button>
        <button class="ghost" data-act="false_alarm" data-id="${e.id}">False alarm</button>
        ${e.evidence_clip_url ? `<button class="ghost" data-act="clip" data-id="${e.id}">Clip</button>` : ""}
      </div>
    </div></div>`;
}

async function act(id, action) {
  try {
    if (action === "clip") return playClip(EVENTS[id]);
    if (action === "ack") {
      await OE.api(`/events/${id}/ack`, { method: "POST", json: { note: "acknowledged from control room" } });
    } else if (action === "escalate") {
      await OE.api(`/events/${id}/escalate`, { method: "POST", json: { reason: "escalated by control room" } });
    } else {
      await OE.api(`/events/${id}/outcome`, { method: "POST", json: { outcome: action } });
    }
    refreshIncidents(); refreshMetrics();
  } catch (e) { OE.toast(e.message, "err"); }
}

async function playClip(e) {
  if (!e || !e.evidence_clip_url) return;
  $("clipTitle").textContent =
    `Evidence · ${OE.camName(e.camera_id)} · ${new Date(e.created_at).toLocaleTimeString()}`;
  $("clipModal").classList.add("open");
  try { $("clipVideo").src = await OE.blobUrl(e.evidence_clip_url, "clip"); }
  catch { OE.toast("clip unavailable", "err"); }
}

function renderHistory(events) {
  events.forEach((e) => (EVENTS[e.id] = e));
  const f = $("histFilter").value;
  const rows = events.filter((e) => !f || e.status === f).slice(0, 60);
  $("history").innerHTML =
    "<tr><th>Time</th><th>Camera</th><th>Status</th><th>Risk</th><th>Signals</th><th>Time to ack</th><th>Outcome by</th></tr>"
    + rows.map((e) => `<tr>
        <td>${new Date(e.created_at).toLocaleString()}</td>
        <td>${OE.esc(OE.camName(e.camera_id))}</td>
        <td><span class="status ${e.status}">${e.status.replace("_", " ")}</span></td>
        <td class="lvl ${e.risk_level || ""}">${OE.pct(e.risk_score)}</td>
        <td>${e.distress_signals.map(OE.signal).join(", ")
            || ((e.reason || "").startsWith("DEMO") ? "demo" : "–")}</td>
        <td>${e.acknowledgement
            ? OE.secs((new Date(e.acknowledgement.at) - new Date(e.created_at)) / 1000) : "–"}</td>
        <td>${OE.esc(e.acknowledgement ? e.acknowledgement.by : "")}</td></tr>`).join("");
}
$("histFilter").onchange = refreshIncidents;

/* ====================================== alerting: this PC to the phones ==
   The chain is PC -> API -> push service -> phone, and every link can be missing: no https, no
   VAPID keys, no phone registered, notifications denied on the handset. Rather than describe the
   chain, this panel shows which links exist and can send a real notification through all of them. */

function chainStep(label, ok) {
  return `<span class="pill"><span class="dot ${ok ? "on" : "off"}"></span>${OE.esc(label)}</span>`;
}

async function refreshAlerting() {
  const caps = CFG.capabilities || {};
  let note = "";
  if (!caps.web_push) {
    note = caps.secure_context
      ? "Background alerts are off: this server has no VAPID keys. Run "
        + "<span class='mono'>python scripts/make_push_keys.py</span>, put the keys in "
        + "<span class='mono'>.env</span> and restart."
      : "Background alerts need https. Start the API with <span class='mono'>--https</span> and open the "
        + "https address on the phone; over plain http a phone only alerts while the app is open.";
  }
  try {
    DEVICES = await OE.api("/push/devices");
  } catch (e) {
    DEVICES = [];
    note = note || OE.esc(e.message);
  }
  const rows = DEVICES.map((d) => `<div class="row">
      <div><b>${OE.esc(d.label || "phone")}</b>
        <div class="small">${OE.esc(d.role)} · <span class="mono">${OE.esc(d.endpoint_hash.slice(0, 12))}</span>${
          d.consecutive_failures ? ` · ${d.consecutive_failures} failed delivery attempt(s)` : ""}</div></div>
      <span class="chip">${d.consecutive_failures ? "unhealthy" : "ready"}</span>
    </div>`).join("");

  $("alertStatus").innerHTML = `
    <div class="btns">
      ${chainStep("Secure connection (https)", caps.secure_context)}
      ${chainStep("Background push configured", caps.web_push)}
      ${chainStep(`Phones registered (${DEVICES.length})`, DEVICES.length > 0)}
    </div>
    ${note ? `<p class="note warn" style="margin-top:10px">${note}</p>` : ""}
    <div class="results" style="margin-top:10px">${rows
      || '<div class="small">No phones registered yet. On the phone, open the lifeguard app and tap '
         + '“Turn alerts on” — it appears here within a few seconds.</div>'}</div>`;
  $("k-phones").querySelector(".v").textContent = DEVICES.length;
  $("k-phones").classList.toggle("alert", Boolean(caps.web_push) && DEVICES.length === 0);
}

$("refreshPhones").onclick = () => refreshAlerting();

$("testPhones").onclick = async () => {
  $("testResult").textContent = "Sending…";
  $("testPhones").disabled = true;
  try {
    const r = await OE.api("/push/test", { method: "POST" });
    $("testResult").innerHTML = r.sent
      ? `Delivered to <b>${r.sent}</b> of ${r.devices} phone(s). It arrives as “OceanEye test alert”, `
        + "does not sound the alarm, and is not recorded as an incident."
        + `<div class="small mono">${OE.esc(r.detail || "")}</div>`
      : `<b>Not delivered.</b> ${OE.esc(r.detail || "")}`;
  } catch (e) {
    $("testResult").innerHTML = `<b>Not delivered.</b> ${OE.esc(e.message)}`;
  } finally {
    $("testPhones").disabled = false;
    refreshAlerting();
  }
};

/* ============================================================== metrics == */

async function refreshMetrics() {
  const m = await OE.api("/metrics");
  const set = (id, v, alert) => {
    $(id).querySelector(".v").textContent = v;
    $(id).classList.toggle("alert", Boolean(alert));
  };
  set("k-active", m.events.active, m.events.active > 0);
  set("k-cams", `${m.cameras.online}/${Object.keys(OE.cameras).length}`);
  set("k-people", m.cameras.people_now);
  set("k-ack", OE.secs(m.response.time_to_ack.median_s));
  set("k-fa", OE.pct(m.events.false_alarm_rate));

  const t = m.response.time_to_ack;
  $("metrics").innerHTML = `<table>
    <tr><th colspan="2">Response — distress signal to acknowledged response</th></tr>
    <tr><td>acknowledged events</td><td>${t.count}</td></tr>
    <tr><td>time to ack · mean / median / p90 / max</td>
        <td>${OE.secs(t.mean_s)} / ${OE.secs(t.median_s)} / ${OE.secs(t.p90_s)} / ${OE.secs(t.max_s)}</td></tr>
    <tr><td>escalated share</td><td>${OE.pct(m.response.escalated_share)}</td></tr>
    <tr><td>events total · demo</td><td>${m.events.total} · ${m.events.demo_events}</td></tr>
    <tr><td>by status</td><td>${Object.entries(m.events.by_status)
          .map(([k, v]) => `${k.replace("_", " ")} ${v}`).join(" · ")}</td></tr>
    <tr><td>signals seen</td><td>${Object.entries(m.events.signals)
          .map(([k, v]) => `${OE.signal(k)} ${v}`).join(" · ") || "–"}</td></tr>
    <tr><th colspan="2">Detection performance</th></tr>
    ${Object.entries(m.cameras.fps).map(([c, f]) =>
      `<tr><td>${OE.esc(OE.camName(c))}</td><td>${f ?? "–"} fps · ${m.cameras.latency_ms[c] ?? "–"} ms/frame</td></tr>`
    ).join("") || '<tr><td colspan="2">no live cameras</td></tr>'}
    <tr><td>completed video jobs</td>
        <td>${m.jobs.completed} · avg ${m.jobs.avg_pipeline_fps ?? "–"} fps · ${m.jobs.frames_processed} frames</td></tr>
    </table>
    <p class="note">False-alarm rate = false alarms ÷ closed events. Mark every event Resolved or
    False alarm — those outcomes are the labelled data used to tune thresholds and, later, train a model.</p>`;
}

/* ======================================================= map and weather == */

function initMap() {
  if (!window.L) {
    $("map").innerHTML = '<div class="empty">Map library could not load (offline).</div>';
    return;
  }
  const centre = BEACH ? [BEACH.lat, BEACH.lon] : [CFG.lat, CFG.lon];
  map = L.map("map").setView(centre, 14);

  // Tiles come through this application (app/environment/api/tiles.py), not straight from the
  // provider: the API key stays on the server and never reaches the browser.
  const m = (CFG && CFG.map) || {};
  const base = L.tileLayer(m.tile_url, { maxZoom: m.max_zoom || 19, attribution: m.attribution || "" });
  const satellite = m.satellite_url
    ? L.tileLayer(m.satellite_url, { maxZoom: m.max_zoom || 19, attribution: m.satellite_attribution || "" })
    : null;

  base.addTo(map);
  if (satellite) {
    // Satellite shows the actual shoreline and water, which is what makes a camera position make
    // sense; the plain map keeps the markers legible. Both are one click apart.
    L.control.layers({ Map: base, Satellite: satellite }, {}, { position: "topright" }).addTo(map);
  }

  let tileFailures = 0;
  base.on("tileerror", () => {
    tileFailures += 1;
    if (tileFailures === 8) {   // a couple of dropped tiles is normal; a wall of them is not
      // Do not name a single cause here: a wall of tile errors is equally an unset key, an
      // unreachable provider, or a beach stored without coordinates.
      OE.toast("Map tiles are not loading — check OCEANEYE_GEOAPIFY_API_KEY, this host's internet "
               + "access, and that the deployment site has real coordinates", "err");
    }
  });
  base.on("tileload", () => { tileFailures = 0; });

  layers.cams = L.layerGroup().addTo(map);
  layers.inc = L.layerGroup().addTo(map);
  layers.beach = L.layerGroup().addTo(map);
  if (BEACH) {
    L.circleMarker(centre, { radius: 10, color: "#0f5d7a", fillColor: "#0f5d7a", fillOpacity: 0.9, weight: 3 })
      .bindTooltip(`${BEACH.name} — this deployment`).addTo(layers.beach);
  }
  map.on("click", (e) => {
    const lat = e.latlng.lat.toFixed(5);
    const lon = e.latlng.lng.toFixed(5);
    $("cLat").value = lat; $("cLon").value = lon;   // a new camera
    $("sLat").value = lat; $("sLon").value = lon;   // or a beach typed in by hand
    OE.toast(`Picked ${lat}, ${lon}`);
  });
}

function drawMap() {
  if (!map) return;
  layers.cams.clearLayers();
  Object.values(OE.cameras).forEach((c) =>
    L.circleMarker([c.lat, c.lon], { radius: 7, color: "#16150f", fillColor: "#7cc6e0", fillOpacity: 0.95, weight: 2 })
      .bindTooltip(OE.esc(c.name)).addTo(layers.cams));
}

function drawIncidentMarkers(active) {
  if (!map) return;
  layers.inc.clearLayers();
  active.forEach((e) =>
    L.circleMarker([e.location.lat, e.location.lon],
                   { radius: 15, color: "#b3221c", fillColor: "#b3221c", fillOpacity: 0.3, weight: 3 })
      .bindTooltip(`${OE.esc(OE.camName(e.camera_id))} · ${e.status} · ${OE.pct(e.risk_score)}`)
      .addTo(layers.inc));
}

/** Where this installation is, in words and in coordinates, so the location is stated rather than
 *  implied by wherever the map happens to be centred. */
function renderMapNote() {
  if (!BEACH) {
    $("mapNote").textContent = "no beach set";
    $("beachInfo").textContent = "";
    return;
  }
  $("mapNote").textContent = `${BEACH.lat.toFixed(4)}, ${BEACH.lon.toFixed(4)}`;
  $("beachInfo").innerHTML = `<b>${OE.esc(BEACH.name)}</b> — ${OE.esc(BEACH.region || "area not recorded")}`;
}

/** Neighbouring beaches, drawn faintly. Purely informational: nothing is watched unless it has a
 *  camera attached to this deployment. */
async function loadNeighbours() {
  if (!BEACH || !(CFG.capabilities || {}).place_search) return;
  try {
    const body = await OE.api(`/places/beaches-near?lat=${BEACH.lat}&lon=${BEACH.lon}&radius_km=20`);
    if (!body.results.length) return;
    $("beachInfo").innerHTML += `<div class="small">${body.results.length} other beach(es) within 20 km: `
      + body.results.slice(0, 5).map((x) => `${OE.esc(x.name)} (${x.distance_km} km)`).join(", ") + "</div>";
    if (map) {
      body.results.forEach((x) =>
        L.circleMarker([x.lat, x.lon], { radius: 5, color: "#9a6200", fillOpacity: 0.7, weight: 2 })
          .bindTooltip(`${OE.esc(x.name)} · ${x.distance_km} km`).addTo(layers.beach));
    }
  } catch { /* informational only */ }
}

async function loadWeather() {
  const lat = BEACH ? BEACH.lat : CFG.lat;
  const lon = BEACH ? BEACH.lon : CFG.lon;
  try {
    const w = await OE.api(`/weather?lat=${lat}&lon=${lon}`);
    $("wxStatus").textContent = `${w.source} · ${w.status}${w.status !== "ok" && w.error ? ` (${w.error})` : ""}`;
    const cell = (l, v) => `<div><span class="small">${l}</span><b>${v}</b></div>`;
    $("wx").innerHTML = cell("Wind", OE.num(w.wind_speed_ms, 1, " m/s"))
      + cell("Gusts", OE.num(w.wind_gusts_ms, 1, " m/s"))
      + cell("Waves", OE.num(w.wave_height_m, 1, " m"))
      + cell("Swell", OE.num(w.swell_height_m, 1, " m"))
      + cell("Sea level (tide)", OE.num(w.tide_height_m, 2, " m"))
      + cell("Wave period", OE.num(w.wave_period_s, 0, " s"))
      + cell("Sea temp", OE.num(w.sea_surface_temperature_c, 1, " °C"))
      + cell("Air temp", OE.num(w.air_temperature_c, 1, " °C"))
      + cell("Sky", OE.weather(w.weather_code));
    $("fc").innerHTML =
      "<tr><th>Hour</th><th>Wind</th><th>Gust</th><th>Waves</th><th>Swell</th><th>Sea lvl</th><th>Rain %</th></tr>"
      + w.forecast.map((p) => `<tr><td>${p.time.slice(11, 16)}</td><td>${OE.num(p.wind_speed_ms)}</td>
          <td>${OE.num(p.wind_gusts_ms)}</td><td>${OE.num(p.wave_height_m)}</td>
          <td>${OE.num(p.swell_height_m)}</td><td>${OE.num(p.sea_level_m, 2)}</td>
          <td>${p.precipitation_prob ?? "–"}</td></tr>`).join("");
  } catch (e) { $("wxStatus").textContent = e.message; }
}

/* ====================================================== video analysis ==
   Moved here from a page of its own: a recorded clip runs through the same worker, the same
   detection, tracking, zone and risk code, and raises the same events - which is the only way to
   test the full alert path, lifeguard phones included, without standing on a beach. */

async function loadUploads() {
  UPLOADS = await OE.api("/uploads").catch(() => []);
  $("aUpload").innerHTML = UPLOADS.map((u) => `<option value="${u.id}">${OE.esc(u.filename)}</option>`).join("")
    || "<option value=''>upload a video first</option>";
  $("uploads").innerHTML = "<tr><th>File</th><th>Size</th><th>Uploaded</th><th></th></tr>"
    + UPLOADS.map((u) => `<tr>
        <td>${OE.esc(u.filename)}</td>
        <td>${(u.size_bytes / 1e6).toFixed(1)} MB</td>
        <td>${OE.ago(u.created_at)}</td>
        <td><button class="ghost" data-cctv="${u.id}" data-name="${OE.esc(u.filename)}">Use as simulated CCTV</button>
            <button class="ghost" data-del="${u.id}" data-name="${OE.esc(u.filename)}">Delete</button></td>
      </tr>`).join("");
  $("uploads").querySelectorAll("[data-cctv]").forEach((b) =>
    (b.onclick = () => makeSimulatedCamera(b.dataset.cctv, b.dataset.name)));
  $("uploads").querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm(`Delete "${b.dataset.name}" and its file?`)) return;
    try {
      await OE.api(`/uploads/${b.dataset.del}`, { method: "DELETE" });
      OE.toast("Clip deleted");
      await loadUploads();
      loadJobs();
    } catch (e) {
      // 409 means something still depends on it - the message names what, so show it as-is.
      OE.toast(e.message, "err");
    }
  }));
}

function loadAnalysisCameras() {
  const cams = Object.values(OE.cameras);
  const here = BEACH ? BEACH.name : CFG.location_name;
  const current = $("aCam").value;
  $("aCam").innerHTML = cams.map((c) => `<option value="${c.id}">${OE.esc(c.name)}</option>`).join("")
    + `<option value="__new">+ new analysis camera at ${OE.esc(here)}</option>`;
  if (current && [...$("aCam").options].some((o) => o.value === current)) $("aCam").value = current;
}

async function makeSimulatedCamera(uploadId, name) {
  const label = prompt("Camera name for this simulated CCTV feed:",
                       "CCTV " + name.replace(/\.[^.]+$/, "").slice(0, 40));
  if (!label) return;
  // Spread markers a little along the coast so the map does not stack them on one point.
  const n = Object.keys(OE.cameras).length;
  const base = BEACH || CFG;
  try {
    await OE.api("/cameras", {
      method: "POST",
      json: {
        name: label,
        lat: +(base.lat + 0.004 * n).toFixed(5),
        lon: +(base.lon - 0.001 * n).toFixed(5),
        video_upload_id: uploadId,
        ...(BEACH ? { beach_id: BEACH.id } : {}),
      },
    });
    OE.toast("Camera created — draw its danger zone on the camera wall, then start monitoring");
    await refreshCameras();
    loadAnalysisCameras(); drawMap();
  } catch (e) { OE.toast(e.message, "err"); }
}

$("upClear").onclick = () => {
  $("file").value = "";
  $("upText").textContent = "";
  $("upProg").style.width = "0";
};

/** Put the analysis controls back to the settings the worker picks for this machine. Three
 *  dropdowns left on a hand-tuned combination is the usual reason a run fails on a small GPU. */
$("aReset").onclick = () => {
  $("aModel").value = "auto";
  $("aImg").value = "0";
  $("aSens").value = "medium";
  $("aDev").value = "auto";
  OE.toast("Analysis settings back to auto");
};

$("upBtn").onclick = async () => {
  const files = [...$("file").files];
  if (!files.length) return OE.toast("Choose a video first", "err");
  for (const [i, f] of files.entries()) {
    // XHR rather than fetch: upload progress has no fetch equivalent, and a 500 MB clip needs a bar.
    await new Promise((resolve) => {
      const fd = new FormData();
      fd.append("file", f);
      const x = new XMLHttpRequest();
      x.open("POST", "/api/uploads");
      Object.entries(OE.headers()).forEach(([k, v]) => x.setRequestHeader(k, v));
      x.upload.onprogress = (e) => {
        $("upProg").style.width = `${(100 * e.loaded / e.total).toFixed(0)}%`;
        $("upText").textContent = `${f.name} (${i + 1}/${files.length})`;
      };
      x.onload = () => {
        if (x.status >= 300) {
          let m = x.statusText;
          try { m = JSON.parse(x.responseText).error.message; } catch { /* keep statusText */ }
          OE.toast(`${f.name}: ${m}`, "err");
        }
        resolve();
      };
      x.onerror = () => { OE.toast("upload failed", "err"); resolve(); };
      x.send(fd);
    });
  }
  $("upText").textContent = "done";
  $("upProg").style.width = "0";
  loadUploads();
};

$("aGo").onclick = async () => {
  let cam = $("aCam").value;
  if (!$("aUpload").value) return OE.toast("Upload a video first", "err");
  try {
    if (cam === "__new") {
      const base = BEACH || CFG;
      cam = (await OE.api("/cameras", {
        method: "POST",
        json: {
          name: "Upload analysis", lat: base.lat, lon: base.lon,
          stream_url: "mock://upload-analysis", source_type: "mock",
          ...(BEACH ? { beach_id: BEACH.id } : {}),
        },
      })).id;
      await refreshCameras();
      loadAnalysisCameras();
    }
    await OE.api("/analysis/jobs", {
      method: "POST",
      json: {
        upload_id: $("aUpload").value, camera_id: cam, model: $("aModel").value,
        imgsz: Number($("aImg").value), sensitivity: $("aSens").value, device: $("aDev").value,
      },
    });
    OE.toast("Analysis started — the first progress appears once the model has loaded");
    loadJobs();
  } catch (e) { OE.toast(e.message, "err"); }
};

function jobRow(j, uploadNames) {
  const s = j.summary || {};
  const opts = j.options || {};
  const model = opts.model === "auto" ? (s.model || "auto") : opts.model;
  const imgsz = opts.imgsz || s.imgsz || "auto";
  const speed = s.pipeline_fps
    ? `${s.pipeline_fps} fps${s.warmup_s ? ` · ${s.warmup_s}s warm-up` : ""}` : "–";
  return `<tr>
    <td>${OE.esc(uploadNames[j.upload_id] || j.upload_id)}</td>
    <td>${OE.esc(OE.camName(j.camera_id))}</td>
    <td><span class="status ${j.status}">${j.status}</span></td>
    <td><div class="progress"><i style="width:${(j.progress * 100).toFixed(0)}%"></i></div></td>
    <td>${OE.esc(String(model))} @${imgsz}${s.device ? ` · ${OE.esc(s.device)}` : ""} · ${OE.esc(opts.sensitivity || "")}</td>
    <td>${speed}</td>
    <td>${s.max_concurrent_people ?? "–"}</td>
    <td>${s.unique_track_ids ?? "–"}</td>
    <td>${j.events_created}</td>
    <td>${j.video_url ? `<button data-v="${j.id}" data-u="${j.video_url}">Watch</button>` : ""}
        ${["queued", "running"].includes(j.status) ? `<button class="ghost" data-c="${j.id}">Cancel</button>`
                                                     : `<button class="ghost" data-rm="${j.id}">Remove</button>`}
        ${j.error ? `<span class="small" title="${OE.esc(j.error)}">${OE.esc(j.error.slice(0, 70))}</span>` : ""}</td>
  </tr>`;
}

async function loadJobs() {
  const jobs = await OE.api("/analysis/jobs").catch(() => []);
  const uploadNames = Object.fromEntries(UPLOADS.map((u) => [u.id, u.filename]));
  $("jobs").innerHTML =
    "<tr><th>Video</th><th>Camera</th><th>Status</th><th>Progress</th><th>Model</th><th>Speed</th>"
    + "<th>People (max)</th><th>Track IDs</th><th>Events</th><th></th></tr>"
    + jobs.map((j) => jobRow(j, uploadNames)).join("");

  $("jobs").querySelectorAll("[data-v]").forEach((b) => (b.onclick = async () => {
    $("vidTitle").textContent = "Annotated result";
    $("vidModal").classList.add("open");
    $("vid").src = await OE.blobUrl(b.dataset.u, "job");
  }));
  $("jobs").querySelectorAll("[data-c]").forEach((b) => (b.onclick = async () => {
    await OE.api(`/analysis/jobs/${b.dataset.c}/cancel`, { method: "POST" });
    loadJobs();
  }));
  $("jobs").querySelectorAll("[data-rm]").forEach((b) => (b.onclick = async () => {
    try {
      await OE.api(`/analysis/jobs/${b.dataset.rm}`, { method: "DELETE" });
      loadJobs();
    } catch (e) { OE.toast(e.message, "err"); }
  }));
}

/** Remove every finished run. Deliberately confirmed: the job table is the only record of what
 *  the pipeline did, and a run that took ten minutes is not worth losing to a stray click. */
$("jobsClear").onclick = async () => {
  if (!confirm("Remove every completed, failed and cancelled analysis job?\n\n"
               + "Running jobs are left alone. Events, evidence and alerts are not touched.")) return;
  try {
    const r = await OE.api("/analysis/jobs/clear-finished", { method: "POST" });
    OE.toast(`${r.removed} finished job(s) removed`);
    loadJobs();
  } catch (e) { OE.toast(e.message, "err"); }
};

/** Default the analysis form to what the server is configured for, and say plainly what this
 *  machine can do - a CPU-only box produces a few frames per second, which is worth knowing before
 *  queueing a ten-minute clip. */
function describeMachine() {
  const hw = CFG.hardware || {};
  $("aModel").value = CFG.worker.model || "auto";
  $("aImg").value = String(CFG.worker.imgsz || 0);
  $("aSens").value = CFG.worker.sensitivity || "medium";
  $("aDev").value = CFG.worker.device || "auto";
  const note = $("autoNote");
  note.style.display = "";
  if (hw.gpu) {
    note.className = "note";
    note.innerHTML = `Detected <b>${OE.esc(hw.gpu)}</b>${hw.vram_gb ? ` with ${hw.vram_gb} GB VRAM` : ""}`
      + ` · ${CFG.max_workers} worker slot(s). On <b>auto</b> the worker picks a model and image size`
      + " that fit this GPU, so leave it there unless you are comparing models deliberately.";
  } else {
    note.className = "note warn";
    note.innerHTML = "No GPU detected on this machine. Analysis runs on the CPU, which is several times "
      + "slower — leave the model and image size on <b>auto</b> and expect a few frames per second. "
      + "For faster runs use the Colab notebook "
      + "(<span class='mono'>notebooks/OceanEye_Perception_Colab.ipynb</span>).";
  }
}

/* ========================================================= live updates == */

function onWs(msg) {
  if (!msg.type || !msg.type.startsWith("alert.")) return;
  const p = msg.payload;
  if (p && p.event_id === "test") {   // the connection check, not an incident
    OE.toast("Test alert reached this control room too.");
    return;
  }
  if (msg.type === "alert.created") {
    OE.toast(`New incident — ${OE.camName(p.camera_id)} (${OE.pct(p.risk_score)})`, "alert");
    OE.beep(3);
  }
  if (msg.type === "alert.escalated") {
    OE.toast(`Escalated — ${OE.camName(p.camera_id)}`, "alert");
    OE.beep(2, 600);
  }
  refreshIncidents(); refreshMetrics();
}

(async function start() {
  try {
    CFG = await OE.loadConfig();
    BEACH = CFG.beach;
  } catch (e) {
    OE.toast(`API error: ${e.message} (role ${OE.role})`, "err");
    return;
  }
  if (BEACH) {
    try { BEACH = await OE.api("/beaches/active"); } catch { /* keep the config copy */ }
  }
  renderSite();
  initMap();
  renderMapNote();
  await refreshCameras();
  drawMap();
  loadAnalysisCameras();
  describeMachine();
  await loadUploads();
  loadJobs();
  refreshIncidents(); refreshMetrics(); refreshAlerting(); loadWeather(); loadNeighbours();
  OE.connect(onWs, (on) => {
    $("wsdot").className = `dot ${on ? "on" : "off"}`;
    $("wstext").textContent = on ? "live alerts" : "reconnecting…";
  });
  setInterval(refreshCameras, 2000);
  setInterval(refreshFrames, 1000);
  setInterval(refreshIncidents, 5000);
  setInterval(loadJobs, 3000);
  setInterval(refreshMetrics, 10000);
  setInterval(refreshAlerting, 20000);
  setInterval(loadWeather, 600000);
})();
