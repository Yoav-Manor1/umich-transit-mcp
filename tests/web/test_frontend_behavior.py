"""Execute the browser script against a small DOM harness to protect UI state."""

import subprocess
from pathlib import Path

APP_JS = Path(__file__).parents[2] / "src" / "umich_transit" / "web" / "static" / "app.js"

HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

const elements = new Map();
function makeElement(tag = "div") {
  return {
    tagName: tag.toUpperCase(), style: {}, textContent: "", innerHTML: "",
    children: [], className: "", value: "", onclick: null,
    append(...nodes) { this.children.push(...nodes); },
    appendChild(node) { this.children.push(node); return node; },
    setAttribute() {},
    querySelector() { return makeElement(); },
    classList: { toggle() {} },
  };
}
function element(id) {
  if (!elements.has(id)) elements.set(id, makeElement());
  return elements.get(id);
}
global.document = {
  getElementById: element,
  createElement: makeElement,
  createTextNode(text) { return { textContent: text }; },
  addEventListener() {},
};
global.window = {
  location: { origin: "https://example.test" },
  addEventListener() {},
};
const storage = new Map([
  ["umt_selected", "CCTC"],
  ["umt_favorites", JSON.stringify([
    { stop_id: "CCTC", name: "Central Campus Transit Center", walk_min: 5 }
  ])],
]);
global.localStorage = {
  getItem(key) { return storage.has(key) ? storage.get(key) : null; },
  setItem(key, value) { storage.set(key, String(value)); },
  removeItem(key) { storage.delete(key); },
};

vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"), { filename: process.argv[1] });
"""


def _run_node(scenario: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "-e", HARNESS + scenario, str(APP_JS)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_upstream_error_payload_preserves_last_successful_board():
    scenario = r"""
element("arrivals").innerHTML = "last successful board";
element("stop-name").textContent = "Central Campus Transit Center";
global.fetch = async () => ({
  ok: true,
  json: async () => ({
    stop_id: "CCTC", arrivals: [], leave: null, error: "upstream",
    observation: { status: "unknown" }, data_source: "live_bus_time"
  }),
});
(async () => {
  await refresh();
  assert.equal(element("arrivals").innerHTML, "last successful board");
  assert.equal(element("stop-name").textContent, "Central Campus Transit Center");
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""

    result = _run_node(scenario)

    assert result.returncode == 0, result.stderr


def test_stale_observation_is_rendered_instead_of_request_time():
    scenario = r"""
global.fetch = async () => ({
  ok: true,
  json: async () => ({
    stop_id: "CCTC", now: "2026-05-01T18:00:00Z", arrivals: [], leave: null,
    data_source: "live_bus_time",
    observation: {
      status: "stale", observed_at: "2026-05-01T17:54:00Z",
      age_seconds: 360, stale_after_seconds: 300
    }
  }),
});
(async () => {
  await refresh();
  assert.match(element("updated").textContent, /^Stale data/);
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""

    result = _run_node(scenario)

    assert result.returncode == 0, result.stderr


def test_search_suggestion_is_an_accessible_button_that_selects_without_a_dialog():
    scenario = r"""
let pendingSearch;
global.setTimeout = (callback) => { pendingSearch = callback(); return 1; };
global.clearTimeout = () => {};
global.prompt = () => { throw new Error("selection must not require a modal dialog"); };
global.fetch = async (url) => {
  if (url.pathname === "/api/stops/search") {
    return { ok: true, json: async () => ({
      stops: [{ id: "PIER", name: "Pierpont Commons" }]
    }) };
  }
  return { ok: true, json: async () => ({
    stop_id: "PIER", now: "2026-05-01T18:00:00Z", arrivals: [], leave: null,
    data_source: "demo", observation: { status: "demo" }
  }) };
};
(async () => {
  onSearch({ target: { value: "Pierpont" } });
  await pendingSearch;
  const suggestion = element("results").children[0];
  assert.equal(suggestion.tagName, "BUTTON");
  suggestion.onclick();
  assert.equal(storage.get("umt_selected"), "PIER");
  assert.equal(element("search").value, "");
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""

    result = _run_node(scenario)

    assert result.returncode == 0, result.stderr
