const LS_FAVS = "umt_favorites";
const LS_SEL = "umt_selected";
let refreshTimer = null;
let searchTimer = null;
let appMode = "local";

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

function fmtDuration(seconds) {
  const minutes = Math.round(seconds / 60);
  return `${minutes} min`;
}

async function api(path, params) {
  const url = new URL(path, window.location.origin);
  Object.entries(params || {}).forEach(([key, value]) => url.searchParams.set(key, value));
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

function currentWalk() {
  const favorite = loadFavs().find((item) => item.stop_id === getSelected());
  return favorite ? favorite.walk_min : 5;
}

function renderChips() {
  const favorites = loadFavs();
  const selected = getSelected();
  const container = document.getElementById("chips");
  container.innerHTML = "";
  favorites.forEach((favorite) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `chip${favorite.stop_id === selected ? " active" : ""}`;
    chip.append(document.createTextNode(favorite.name));
    chip.onclick = () => {
      setSelected(favorite.stop_id);
      renderChips();
      refresh();
    };

    const remove = document.createElement("span");
    remove.className = "chip-x";
    remove.setAttribute("aria-label", `Remove ${favorite.name}`);
    remove.textContent = "×";
    remove.onclick = (event) => {
      event.stopPropagation();
      removeFav(favorite.stop_id);
    };
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

function addFav(stop, walkOverride = null) {
  const favorites = loadFavs();
  if (!favorites.some((favorite) => favorite.stop_id === stop.id)) {
    let walk = walkOverride;
    if (walk === null) {
      const raw = prompt(`Minutes to walk to "${stop.name}"?`, "5");
      const parsed = parseInt(raw, 10);
      walk = Number.isNaN(parsed) ? 5 : parsed;
    }
    favorites.push({ stop_id: stop.id, name: stop.name, walk_min: walk });
    saveFavs(favorites);
  }
  setSelected(stop.id);
  document.getElementById("search").value = "";
  document.getElementById("results").innerHTML = "";
  renderChips();
  refresh();
}

function onSearch(event) {
  clearTimeout(searchTimer);
  const query = event.target.value.trim();
  const results = document.getElementById("results");
  if (!query) { results.innerHTML = ""; return; }
  searchTimer = setTimeout(async () => {
    try {
      const data = await api("/api/stops/search", { q: query, limit: 8 });
      results.innerHTML = "";
      (data.stops || []).forEach((stop) => {
        const item = document.createElement("div");
        item.className = "result";
        item.textContent = stop.name;
        item.onclick = () => addFav(stop);
        results.appendChild(item);
      });
    } catch {
      setNote("Stop search is temporarily unavailable.");
    }
  }, 250);
}

function setNote(text) {
  const note = document.getElementById("note");
  note.textContent = text;
  note.style.display = text ? "block" : "none";
}

function renderBanner(leave) {
  const banner = document.getElementById("banner");
  if (!leave) { banner.style.display = "none"; return; }
  banner.style.display = "grid";
  banner.querySelector(".banner-main").textContent =
    leave.leave_in_min <= 0 ? "Leave now" : `Leave in ${leave.leave_in_min} minutes`;
  banner.querySelector(".banner-sub").textContent =
    `Walk ${currentWalk()} minutes to catch ${leave.route_id} at ${fmtClock(leave.arrival_at)}.`;
}

function makeEtaBlock(label, iso, nowIso, adjusted = false) {
  const block = document.createElement("div");
  block.className = `eta-block${adjusted ? " adjusted" : ""}`;
  const value = document.createElement("strong");
  value.textContent = `${minsUntil(iso, nowIso)} min`;
  const clock = document.createElement("small");
  clock.textContent = `${label} · ${fmtClock(iso)}`;
  block.append(value, clock);
  return block;
}

function renderArrivals(arrivals, nowIso) {
  const list = document.getElementById("arrivals");
  list.innerHTML = "";
  if (!arrivals.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = "No upcoming arrivals right now.";
    list.appendChild(empty);
    return;
  }

  arrivals.forEach((arrival) => {
    const row = document.createElement("article");
    row.className = "arrival-row";

    const route = document.createElement("div");
    route.className = "route-pill";
    const dot = document.createElement("span");
    dot.className = "route-dot";
    const routeText = document.createElement("span");
    routeText.textContent = arrival.route_id;
    route.append(dot, routeText);

    const published = makeEtaBlock("Published", arrival.predicted_arrival_at, nowIso);
    const effectiveIso = arrival.confidence === "high"
      ? arrival.adjusted_arrival_at
      : arrival.predicted_arrival_at;
    const adjusted = makeEtaBlock(
      arrival.confidence === "high" ? "Adjusted" : "Published",
      effectiveIso,
      nowIso,
      arrival.confidence === "high"
    );
    const badge = document.createElement("span");
    badge.className = `confidence ${arrival.confidence}`;
    badge.textContent = arrival.confidence === "high"
      ? `${arrival.confidence} · n=${arrival.sample_size}`
      : "low confidence";
    adjusted.appendChild(badge);

    const reason = document.createElement("p");
    reason.className = "reason";
    reason.textContent = arrival.adjustment_reason ||
      (arrival.confidence === "high"
        ? "Historical evidence supports this adjustment."
        : "Showing the published estimate until more history is available.");

    row.append(route, published, adjusted, reason);
    list.appendChild(row);
  });
}

async function refresh() {
  const selected = getSelected();
  const empty = document.getElementById("empty");
  const board = document.getElementById("board");
  if (!selected) {
    empty.style.display = "block";
    board.style.display = "none";
    return;
  }
  empty.style.display = "none";
  board.style.display = "block";

  let data;
  try {
    data = await api("/api/arrivals", {
      stop_id: selected,
      walk_min: currentWalk(),
      limit: 5
    });
  } catch {
    setNote("Could not refresh the arrival feed. Keeping the last visible result.");
    return;
  }
  setNote(data.error ? "The live bus feed is temporarily unavailable." : "");

  const favorite = loadFavs().find((item) => item.stop_id === selected);
  document.getElementById("stop-name").textContent = favorite ? favorite.name : selected;
  document.getElementById("walk-label").textContent = `${currentWalk()} minute walk`;
  renderBanner(data.leave);
  renderArrivals(data.arrivals || [], data.now);
  document.getElementById("updated").textContent = `Updated ${fmtClock(data.now)}`;
}

function renderAccuracy(report) {
  document.getElementById("accuracy-headline").textContent = report.headline;
  document.getElementById("published-mae").textContent =
    fmtDuration(report.published.mean_absolute_error_s);
  document.getElementById("adjusted-mae").textContent =
    fmtDuration(report.adjusted.mean_absolute_error_s);
  document.getElementById("within-two").textContent =
    `${Math.round(report.adjusted.within_two_minutes_pct * 100)}%`;
  document.getElementById("within-two-detail").textContent =
    `${Math.round(report.published.within_two_minutes_pct * 100)}% published`;
  document.getElementById("sample-count").textContent = `${report.sample_count} holdout predictions`;

  const routes = document.getElementById("route-results");
  routes.innerHTML = "";
  (report.routes || []).forEach((route) => {
    const row = document.createElement("div");
    row.className = "route-result";
    const name = document.createElement("span");
    name.textContent = `${route.route_id} · n=${route.sample_count}`;
    const before = document.createElement("span");
    before.textContent = `${fmtDuration(route.published_mae_s)} published`;
    const after = document.createElement("strong");
    after.textContent = `${fmtDuration(route.adjusted_mae_s)} adjusted`;
    row.append(name, before, after);
    routes.appendChild(row);
  });
}

async function loadAccuracy() {
  try {
    renderAccuracy(await api("/api/accuracy"));
  } catch {
    document.getElementById("accuracy-headline").textContent =
      "Accuracy evidence is temporarily unavailable.";
  }
}

function selectTab(tabName) {
  const live = tabName === "live";
  document.getElementById("live-view").hidden = !live;
  document.getElementById("accuracy-view").hidden = live;
  document.getElementById("live-tab").classList.toggle("active", live);
  document.getElementById("accuracy-tab").classList.toggle("active", !live);
  document.getElementById("live-tab").setAttribute("aria-selected", String(live));
  document.getElementById("accuracy-tab").setAttribute("aria-selected", String(!live));
  if (!live) loadAccuracy();
}

async function initializeMode() {
  try {
    const health = await api("/api/health");
    appMode = health.mode || "local";
  } catch {
    appMode = "local";
  }
  const demo = appMode === "demo";
  document.getElementById("demo-notice").style.display = demo ? "flex" : "none";
  document.getElementById("mode-badge").style.display = demo ? "inline-flex" : "none";

  if (demo && !loadFavs().length) {
    saveFavs([{ stop_id: "CCTC", name: "Central Campus Transit Center", walk_min: 5 }]);
    setSelected("CCTC");
  }
}

async function init() {
  document.getElementById("search").addEventListener("input", onSearch);
  document.getElementById("live-tab").addEventListener("click", () => selectTab("live"));
  document.getElementById("accuracy-tab").addEventListener("click", () => selectTab("accuracy"));
  await initializeMode();
  const favorites = loadFavs();
  if (!getSelected() && favorites.length) setSelected(favorites[0].stop_id);
  renderChips();
  refresh();
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(refresh, 60000);
  window.addEventListener("focus", refresh);
}

document.addEventListener("DOMContentLoaded", init);
