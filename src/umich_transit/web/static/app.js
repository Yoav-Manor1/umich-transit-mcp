const LS_FAVS = "umt_favorites";
const LS_SEL = "umt_selected";
let refreshTimer = null;
let searchTimer = null;

function loadFavs() {
  try { return JSON.parse(localStorage.getItem(LS_FAVS)) || []; }
  catch { return []; }
}
function saveFavs(favs) { localStorage.setItem(LS_FAVS, JSON.stringify(favs)); }
function getSelected() { return localStorage.getItem(LS_SEL); }
function setSelected(id) { localStorage.setItem(LS_SEL, id); }

function fmtClock(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}
function minsUntil(iso, nowIso) {
  return Math.max(0, Math.ceil((new Date(iso) - new Date(nowIso)) / 60000));
}

async function api(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([k, v]) => url.searchParams.set(k, v));
  const r = await fetch(url);
  return r.json();
}

function currentWalk() {
  const f = loadFavs().find((x) => x.stop_id === getSelected());
  return f ? f.walk_min : 5;
}

function renderChips() {
  const favs = loadFavs();
  const sel = getSelected();
  const el = document.getElementById("chips");
  el.innerHTML = "";
  favs.forEach((f) => {
    const chip = document.createElement("span");
    chip.className = "chip" + (f.stop_id === sel ? " active" : "");
    chip.textContent = f.name;
    chip.onclick = () => { setSelected(f.stop_id); renderChips(); refresh(); };
    const x = document.createElement("button");
    x.className = "chip-x";
    x.textContent = "×";
    x.onclick = (e) => { e.stopPropagation(); removeFav(f.stop_id); };
    chip.appendChild(x);
    el.appendChild(chip);
  });
}

function removeFav(id) {
  const favs = loadFavs().filter((f) => f.stop_id !== id);
  saveFavs(favs);
  if (getSelected() === id) {
    if (favs.length) setSelected(favs[0].stop_id);
    else localStorage.removeItem(LS_SEL);
  }
  renderChips();
  refresh();
}

function addFav(stop) {
  const favs = loadFavs();
  if (!favs.some((f) => f.stop_id === stop.id)) {
    const raw = prompt(`Minutes to walk to "${stop.name}"?`, "5");
    const walk = parseInt(raw, 10);
    favs.push({ stop_id: stop.id, name: stop.name, walk_min: isNaN(walk) ? 5 : walk });
    saveFavs(favs);
  }
  setSelected(stop.id);
  document.getElementById("search").value = "";
  document.getElementById("results").innerHTML = "";
  renderChips();
  refresh();
}

function onSearch(e) {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  const box = document.getElementById("results");
  if (!q) { box.innerHTML = ""; return; }
  searchTimer = setTimeout(async () => {
    const data = await api("/api/stops/search", { q, limit: 8 });
    box.innerHTML = "";
    (data.stops || []).forEach((s) => {
      const item = document.createElement("div");
      item.className = "result";
      item.textContent = s.name;
      item.onclick = () => addFav(s);
      box.appendChild(item);
    });
  }, 250);
}

function setNote(text) {
  const n = document.getElementById("note");
  n.textContent = text;
  n.style.display = text ? "block" : "none";
}

function renderBanner(leave) {
  const b = document.getElementById("banner");
  if (!leave) { b.style.display = "none"; return; }
  b.style.display = "flex";
  b.querySelector(".banner-main").textContent =
    leave.leave_in_min <= 0 ? "Leave now" : `Leave in ${leave.leave_in_min} min`;
  b.querySelector(".banner-sub").textContent =
    `to catch ${leave.route_id} (arrives ${fmtClock(leave.arrival_at)})`;
}

function renderArrivals(arrivals, nowIso) {
  const list = document.getElementById("arrivals");
  list.innerHTML = "";
  if (!arrivals.length) {
    list.innerHTML = '<div class="muted">No upcoming arrivals right now.</div>';
    return;
  }
  arrivals.forEach((a) => {
    const etaIso = a.confidence === "high" ? a.adjusted_arrival_at : a.predicted_arrival_at;
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML =
      `<span class="route">${a.route_id}</span>` +
      `<span class="right">` +
      `<span class="clock">${fmtClock(a.predicted_arrival_at)}</span>` +
      `<b class="eta">${minsUntil(etaIso, nowIso)} min</b>` +
      `<span class="badge">${a.confidence === "high" ? "history" : "live"}</span>` +
      `</span>`;
    list.appendChild(row);
  });
}

async function refresh() {
  const sel = getSelected();
  const empty = document.getElementById("empty");
  const board = document.getElementById("board");
  if (!sel) { empty.style.display = "block"; board.style.display = "none"; return; }
  empty.style.display = "none";
  board.style.display = "block";

  let data;
  try {
    data = await api("/api/arrivals", { stop_id: sel, walk_min: currentWalk(), limit: 5 });
  } catch {
    setNote("Couldn't refresh — retrying…");
    return;
  }
  setNote(data.error ? "Couldn't reach the bus feed — retrying…" : "");

  const fav = loadFavs().find((x) => x.stop_id === sel);
  document.getElementById("stop-name").textContent = fav ? fav.name : sel;
  document.getElementById("walk-label").textContent = `🚶 ${currentWalk()} min walk`;
  renderBanner(data.leave);
  renderArrivals(data.arrivals || [], data.now);
  document.getElementById("updated").textContent = "Updated " + fmtClock(data.now);
}

function init() {
  document.getElementById("search").addEventListener("input", onSearch);
  const favs = loadFavs();
  if (!getSelected() && favs.length) setSelected(favs[0].stop_id);
  renderChips();
  refresh();
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refresh, 60000);
  window.addEventListener("focus", refresh);
}

document.addEventListener("DOMContentLoaded", init);
