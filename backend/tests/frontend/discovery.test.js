// Job discovery pilot card (frontend/career/js/discovery.js), run in a bare VM with a fake DOM. No network: authedFetch is a
// scripted stub that records each call and fails the test on any unexpected path.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend", "career");
const source = fs.readFileSync(path.join(FRONTEND, "js", "discovery.js"), "utf8");

function makeEl(id) {
  return {
    id, value: "", textContent: "", hidden: false, checked: false, disabled: false, className: "", href: "", target: "", rel: "",
    type: "", name: "", children: [], listeners: {},
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    appendChild(c) { this.children.push(c); return c; },
  };
}

function load(script) {
  const elements = {};
  const getEl = (id) => (elements[id] = elements[id] || makeEl(id));
  const calls = [];
  const sandbox = {
    console, setTimeout, clearTimeout,
    document: {
      getElementById: getEl,
      createElement: (tag) => makeEl(tag),
      createTextNode: (t) => ({ textNode: t }),
      querySelectorAll: () => [],
    },
    authedFetch: async (url, options) => {
      calls.push({ url, options });
      return script(url, options);
    },
    readOpportunityError: async () => "server message",
    formatErrorDetail: () => "",
    loadOpportunities: async () => {},
    compareSavedOpportunity: () => {},
    allOpportunities: [],
    elements,
    calls,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return sandbox;
}

const json = (data, ok = true, status = 200) => ({ ok, status, json: async () => data });

test("the card stays hidden when the server answers 404 (switch off or not allowed)", async () => {
  const world = load(() => json({ detail: "Not found." }, false, 404));
  world.elements["discovery-card"] = makeEl("discovery-card");
  world.elements["discovery-card"].hidden = true;
  await world.loadDiscovery();
  assert.equal(world.elements["discovery-card"].hidden, true);
  assert.equal(world.calls.length, 1);
  assert.equal(world.calls[0].url, "/api/career/job-preferences");
});

test("the card shows the follow list from the server and uses textContent for board names", async () => {
  const prefs = {
    target_titles: ["Program Manager"], locations: ["Chicago"], remote_ok: true, onsite_ok: false, employment_types: ["full_time"],
    exclude_words: [], followed_boards: ["greenhouse:sample-a"], follow_limit: 10,
    available_boards: [{ key: "greenhouse:sample-a", name: "<b>Sample Employer A</b>" }],
  };
  const world = load((url) => (url.endsWith("job-preferences") ? json(prefs) : json({ matches: [], message: "" })));
  world.elements["discovery-card"] = makeEl("discovery-card");
  world.elements["discovery-card"].hidden = true;
  world.elements["discovery-boards"] = makeEl("discovery-boards");
  await world.loadDiscovery();
  assert.equal(world.elements["discovery-card"].hidden, false);
  const label = world.elements["discovery-boards"].children[0];
  assert.equal(label.children[0].checked, true);
  assert.equal(label.children[0].value, "greenhouse:sample-a");
  assert.match(label.children[1].textNode, /<b>Sample Employer A<\/b>/);
});

test("saving preferences sends only the approved preference fields", async () => {
  const world = load((url, options) => {
    if (options && options.method === "PUT") return json({ target_titles: [], locations: [], remote_ok: true, onsite_ok: true, employment_types: [], exclude_words: [], followed_boards: [], follow_limit: 10, available_boards: [] });
    return json({ matches: [], message: "" });
  });
  for (const id of ["discovery-titles", "discovery-locations", "discovery-exclude"]) world.elements[id] = makeEl(id);
  world.elements["discovery-titles"].value = "Program Manager, Project Lead";
  world.elements["discovery-remote"] = makeEl("discovery-remote");
  world.elements["discovery-remote"].checked = true;
  world.elements["discovery-list"] = makeEl("discovery-list");
  let prevented = false;
  await world.saveDiscoveryPreferences({ preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  const put = world.calls.find((c) => c.options && c.options.method === "PUT");
  const body = JSON.parse(put.options.body);
  assert.deepEqual(Object.keys(body).sort(), ["employment_types", "exclude_words", "followed_boards", "locations", "onsite_ok", "remote_ok", "target_titles"]);
  assert.deepEqual(body.target_titles, ["Program Manager", "Project Lead"]);
});

test("the review button posts only the posting fields and then opens the existing compare flow", async () => {
  const opened = [];
  const world = load((url, options) => {
    if (options && options.method === "POST") return json({ id: 7 });
    return json({ matches: [], message: "" });
  });
  world.loadOpportunities = async () => {
    world.allOpportunities = [{ id: 7, job_url: "https://jobs.example-employer.com/sample-a/jobs/1" }];
  };
  world.compareSavedOpportunity = (id) => opened.push(id);
  world.elements["discovery-list"] = makeEl("discovery-list");
  const match = {
    title: "Program Manager", company: "Sample Employer A", location_text: "Chicago, IL", work_arrangement: "on_site",
    employment_type: "full_time", first_seen_on: "2026-11-12", job_url: "https://jobs.example-employer.com/sample-a/jobs/1",
    reasons: ["Title matches a target role"], already_saved: false,
  };
  const button = makeEl("button");
  await world.reviewDiscoveryMatch(match, button);
  const post = world.calls.find((c) => c.options && c.options.method === "POST");
  assert.equal(post.url, "/api/career/opportunities");
  assert.deepEqual(Object.keys(JSON.parse(post.options.body)).sort(), ["employer", "employment_type", "job_url", "location_text", "title", "work_arrangement"]);
  assert.deepEqual(opened, [7]);
});

test("the discovery script never inserts server text as HTML", () => {
  assert.equal(/innerHTML|outerHTML|insertAdjacentHTML|document\.write/.test(source), false);
});
