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
function fmtMinutes(seconds) { return `${(Number(seconds) / 60).toFixed(1)} min`; }

function renderRouteMetrics(routes) {
  const container = document.getElementById("route-metrics");
  container.replaceChildren();
  const entries = Object.entries(routes || {});
  if (!entries.length) return;
  const heading = document.createElement("h3");
  heading.textContent = "Held-out results by route";
  const table = document.createElement("table");
  table.className = "route-table";
  table.innerHTML = "<thead><tr><th>Route</th><th>Published</th><th>Adjusted</th><th>Result</th></tr></thead>";
  const body = document.createElement("tbody");
  entries.forEach(([routeId, comparison]) => {
    const row = document.createElement("tr");
    const route = document.createElement("td");
    route.textContent = routeId;
    const published = document.createElement("td");
    published.textContent = fmtMinutes(comparison.published.mean_absolute_error_s);
    const adjusted = document.createElement("td");
    adjusted.textContent = fmtMinutes(comparison.adjusted.mean_absolute_error_s);
    const result = document.createElement("td");
    result.className = `route-result ${comparison.classification}`;
    result.textContent = comparison.classification;
    row.append(route, published, adjusted, result);
    body.appendChild(row);
  });
  table.appendChild(body);
  container.append(heading, table);
}

async function api(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => url.searchParams.set(key, value));
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

function currentWalk() {
  const favorite = loadFavs().find((item) => item.stop_id === getSelected());
  return favorite ? favorite.walk_min : 5;
}

function updateWalk(value) {
  const parsed = Number.parseInt(value, 10);
  const walk = Number.isFinite(parsed) ? Math.max(0, Math.min(60, parsed)) : 5;
  const selected = getSelected();
  const favorites = loadFavs();
  const favorite = favorites.find((item) => item.stop_id === selected);
  if (!favorite) return;
  favorite.walk_min = walk;
  saveFavs(favorites);
  refresh();
}

function renderChips() {
  const favorites = loadFavs();
  const selected = getSelected();
  const container = document.getElementById("chips");
  container.replaceChildren();
  favorites.forEach((favorite) => {
    const chip = document.createElement("span");
    chip.className = `chip${favorite.stop_id === selected ? " active" : ""}`;
    chip.append(document.createTextNode(favorite.name));
    chip.onclick = () => { setSelected(favorite.stop_id); renderChips(); refresh(); };
    const remove = document.createElement("button");
    remove.className = "chip-x";
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${favorite.name}`);
    remove.textContent = "×";
    remove.onclick = (event) => { event.stopPropagation(); removeFav(favorite.stop_id); };
    chip.appendChild(remove);
    container.appendChild(chip);
  });
}

function removeFav(id) {
  const favorites = loadFavs().filter((favorite) => favorite.stop_id !== id);
  saveFavs(favorites);
  if (getSelected() === id) {
    if (favorites.length) setSelected(favorites[0].stop_id);
    else localStorage.removeItem(LS_SEL);
  }
  renderChips();
  refresh();
}

function addFav(stop) {
  const favorites = loadFavs();
  if (!favorites.some((favorite) => favorite.stop_id === stop.id)) {
    favorites.push({ stop_id: stop.id, name: stop.name, walk_min: 5 });
    saveFavs(favorites);
  }
  setSelected(stop.id);
  document.getElementById("search").value = "";
  document.getElementById("results").replaceChildren();
  renderChips();
  refresh();
}

function onSearch(event) {
  clearTimeout(searchTimer);
  const query = event.target.value.trim();
  const box = document.getElementById("results");
  if (!query) { box.replaceChildren(); return; }
  searchTimer = setTimeout(async () => {
    try {
      const data = await api("/api/stops/search", { q: query, limit: 8 });
      box.replaceChildren();
      (data.stops || []).forEach((stop) => {
        const item = document.createElement("div");
        item.className = "result";
        item.textContent = stop.name;
        item.onclick = () => addFav(stop);
        box.appendChild(item);
      });
    } catch {
      setNote("Stop search is temporarily unavailable.");
    }
  }, 250);
}

function setNote(text) {
  const note = document.getElementById("note");
  note.textContent = text;
  note.hidden = !text;
}

function renderBanner(leave) {
  const banner = document.getElementById("banner");
  if (!leave) { banner.hidden = true; return; }
  banner.hidden = false;
  banner.querySelector(".banner-main").textContent =
    leave.leave_in_min <= 0 ? "Leave now" : `Leave in ${leave.leave_in_min} minutes`;
  banner.querySelector(".banner-sub").textContent =
    `to catch ${leave.route_id}, arriving at ${fmtClock(leave.arrival_at)}`;
}

function renderArrivals(arrivals, nowIso) {
  const container = document.getElementById("arrivals");
  container.replaceChildren();
  if (!arrivals.length) {
    const empty = document.createElement("div");
    empty.className = "muted-row";
    empty.textContent = "No upcoming arrivals right now.";
    container.appendChild(empty);
    return;
  }
  arrivals.forEach((arrival) => {
    const adjusted = arrival.confidence !== "low";
    const effectiveIso = adjusted ? arrival.adjusted_arrival_at : arrival.predicted_arrival_at;
    const row = document.createElement("div");
    row.className = "arrival-row";

    const routeBlock = document.createElement("div");
    routeBlock.className = "route-block";
    const badge = document.createElement("span");
    badge.className = "route-badge";
    badge.textContent = arrival.route_id;
    const routeMeta = document.createElement("div");
    routeMeta.className = "route-meta";
    const vehicle = document.createElement("strong");
    vehicle.textContent = `Vehicle ${arrival.vehicle_id || "—"}`;
    const reason = document.createElement("small");
    reason.className = "reason";
    reason.textContent = arrival.adjustment_reason;
    routeMeta.append(vehicle, reason);
    routeBlock.append(badge, routeMeta);

    const etaBlock = document.createElement("div");
    etaBlock.className = "eta-block";
    const etaMain = document.createElement("div");
    etaMain.className = "eta-main";
    const minutes = document.createElement("strong");
    minutes.textContent = minsUntil(effectiveIso, nowIso);
    const unit = document.createElement("span");
    unit.textContent = "minutes";
    etaMain.append(minutes, unit);
    const comparison = document.createElement("p");
    comparison.className = "eta-comparison";
    comparison.textContent = adjusted
      ? `Published ${fmtClock(arrival.predicted_arrival_at)} → adjusted ${fmtClock(arrival.adjusted_arrival_at)}`
      : `Published arrival ${fmtClock(arrival.predicted_arrival_at)}`;
    const confidence = document.createElement("span");
    confidence.className = `confidence ${arrival.confidence}`;
    confidence.textContent = `${arrival.confidence} confidence · n=${arrival.sample_size}`;
    etaBlock.append(etaMain, comparison, confidence);
    if (arrival.is_stale) {
      const stale = document.createElement("span");
      stale.className = "stale";
      stale.textContent = " · stale feed";
      etaBlock.appendChild(stale);
    }
    row.append(routeBlock, etaBlock);
    container.appendChild(row);
  });
}

async function refresh() {
  const selected = getSelected();
  const empty = document.getElementById("empty");
  const board = document.getElementById("board");
  if (!selected) { empty.hidden = false; board.hidden = true; return; }
  empty.hidden = true;
  board.hidden = false;
  let data;
  try {
    data = await api("/api/arrivals", {
      stop_id: selected, walk_min: currentWalk(), limit: 5,
    });
  } catch {
    setNote("Couldn’t refresh the live feed. Keeping the last good board while we retry.");
    return;
  }
  if (data.error) {
    setNote("Couldn’t reach Magic Bus. Keeping the last good board while we retry.");
    return;
  }
  setNote("");
  const favorite = loadFavs().find((item) => item.stop_id === selected);
  document.getElementById("stop-name").textContent = favorite ? favorite.name : selected;
  document.getElementById("walk-minutes").value = currentWalk();
  renderBanner(data.leave);
  renderArrivals(data.arrivals || [], data.now);
  document.getElementById("updated").textContent = `Updated ${fmtClock(data.now)}`;
}

async function loadAccuracy() {
  const summary = document.getElementById("accuracy-summary");
  const status = document.getElementById("accuracy-status");
  const metrics = document.getElementById("metrics");
  try {
    const report = await api("/api/accuracy");
    if (report.status !== "ready" || !report.metrics) {
      status.textContent = "Building evidence";
      status.className = "status-pill tied";
      summary.textContent = report.summary || "At least 100 matched outcomes are required.";
      metrics.replaceChildren();
      renderRouteMetrics({});
      document.getElementById("evaluation-meta").textContent = "No comparative claim is shown until the holdout is large enough.";
      return;
    }
    const comparison = report.metrics;
    status.textContent = comparison.classification;
    status.className = `status-pill ${comparison.classification}`;
    const published = comparison.published;
    const adjusted = comparison.adjusted;
    const saved = Number(published.mean_absolute_error_s) - Number(adjusted.mean_absolute_error_s);
    summary.textContent =
      `On ${report.holdout_sample_count} future arrivals, the transparent correction was ${comparison.classification}.`;
    metrics.innerHTML = `
      <div class="metric"><small>Published mean error</small><strong>${fmtMinutes(published.mean_absolute_error_s)}</strong></div>
      <div class="metric"><small>Adjusted mean error</small><strong>${fmtMinutes(adjusted.mean_absolute_error_s)}</strong><span class="delta">${fmtMinutes(Math.abs(saved))} ${saved >= 0 ? "less" : "more"} error</span></div>
      <div class="metric"><small>Within two minutes</small><strong>${(Number(adjusted.within_two_minutes_pct) * 100).toFixed(0)}%</strong><span class="delta">after adjustment</span></div>`;
    renderRouteMetrics(comparison.routes);
    document.getElementById("evaluation-meta").textContent =
      `${report.training_sample_count} training · ${report.holdout_sample_count} held out · ${report.match_version} · ${report.model_version}`;
  } catch {
    status.textContent = "Unavailable";
    summary.textContent = "The evaluation report could not be loaded.";
  }
}

function switchView(name) {
  document.querySelectorAll(".view-tab").forEach((tab) => {
    const active = tab.dataset.view === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".view").forEach((view) => view.classList.remove("active"));
  document.getElementById(`${name}-view`).classList.add("active");
  if (name === "accuracy") loadAccuracy();
}

async function loadMeta() {
  try {
    const meta = await api("/api/meta");
    document.getElementById("demo-banner").hidden = !meta.demo_mode;
  } catch {
    document.getElementById("demo-banner").hidden = true;
  }
}

function init() {
  document.getElementById("search").addEventListener("input", onSearch);
  document.getElementById("walk-minutes").addEventListener("change", (event) => {
    updateWalk(event.target.value);
  });
  document.querySelectorAll(".view-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchView(tab.dataset.view));
  });
  const favorites = loadFavs();
  if (!getSelected() && favorites.length) setSelected(favorites[0].stop_id);
  renderChips();
  loadMeta();
  refresh();
  refreshTimer = setInterval(refresh, 60000);
  window.addEventListener("focus", refresh);
}

document.addEventListener("DOMContentLoaded", init);
