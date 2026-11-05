// The dashboard's single "Download my information" button: one button that opens a choice between the readable Word copy and the data backup.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const read = (...p) => fs.readFileSync(path.join(FRONTEND, ...p), "utf8");
const html = read("career", "login.html");
const source = read("career", "js", "exportMenu.js");

test("the dashboard has one Download my information button, with the two downloads inside a hidden choice", () => {
  assert.match(html, /<button type="button" id="export-menu-btn" class="btn-secondary" aria-expanded="false" aria-controls="export-menu">Download my information<\/button>/);
  // a disclosure button: aria-haspopup would announce a "menu", but the choice is a plain group of buttons (no role="menu"/menuitem, no arrow keys)
  assert.ok(!/id="export-menu-btn"[^>]*aria-haspopup/.test(html), "no aria-haspopup on the download button");
  assert.ok(!/role="menu"|role="menuitem"/.test(html.slice(html.indexOf('id="export-menu"'), html.indexOf('id="export-profile-error"'))));
  // real buttons, so Enter and Space work natively and Tab reaches them in order
  assert.match(html, /<button type="button" id="export-readable-btn"/);
  assert.match(html, /<button type="button" id="export-profile-btn"/);
  const menu = html.match(/<div id="export-menu"[^>]*>[\s\S]*?<\/div>/)[0];
  assert.match(menu, /\bhidden\b/);
  assert.match(menu, /role="group" aria-label="Choose a download"/);
  assert.match(menu, /id="export-readable-btn"[^>]*>Download a readable copy \(Word\)<\/button>/);
  assert.match(menu, /id="export-profile-btn"[^>]*>Download data backup \(\.json\)<\/button>/);
  // the two download buttons are not shown outside the choice any more
  const card = html.slice(html.indexOf('class="export-row export-menu-wrap"') - 200, html.indexOf('id="export-profile-error"'));
  assert.strictEqual((card.match(/id="export-readable-btn"/g) || []).length, 1);
  assert.ok(html.includes('<script src="js/exportMenu.js"></script>'));
});

test("the delete panel still offers both copies, with the same ids it presses on the dashboard", () => {
  assert.match(html, /id="delete-readable-btn"[^>]*>Download a readable copy \(Word\)<\/button>/);
  assert.match(html, /id="delete-backup-btn"[^>]*>Download data backup \(\.json\)<\/button>/);
});

// a bare page with just enough behaviour for the menu script
function world() {
  const listeners = { document: {} };
  const focused = [];
  const mkButton = (id) => ({ id, hidden: false, closest: (sel) => (sel === "button" ? mkButton.self : null), focus() { focused.push(id); } });
  const first = { id: "export-readable-btn", focus() { focused.push("export-readable-btn"); } };
  first.closest = (sel) => (sel === "button" ? first : null);
  const attrs = {};
  const toggle = { id: "export-menu-btn", addEventListener(t, f) { listeners.toggle = { [t]: f }; }, setAttribute(k, v) { attrs[k] = v; }, focus() { focused.push("export-menu-btn"); } };
  const menu = { hidden: true, querySelector: () => first, addEventListener(t, f) { listeners.menu = { [t]: f }; } };
  const sandbox = {
    document: {
      getElementById: (id) => ({ "export-menu-btn": toggle, "export-menu": menu })[id] || null,
      addEventListener(t, f) { (listeners.document[t] = listeners.document[t] || []).push(f); },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return { toggle, menu, first, attrs, focused, listeners, outside: { closest: () => null }, inside: { closest: (sel) => (sel === ".export-menu-wrap" ? {} : null) } };
}

test("pressing the button opens the choice, moves focus into it and says so for screen readers", () => {
  const w = world();
  w.listeners.toggle.click();
  assert.strictEqual(w.menu.hidden, false);
  assert.strictEqual(w.attrs["aria-expanded"], "true");
  assert.deepStrictEqual(w.focused, ["export-readable-btn"]);
});

test("pressing it again closes the choice without stealing focus", () => {
  const w = world();
  w.listeners.toggle.click();
  w.focused.length = 0;
  w.listeners.toggle.click();
  assert.strictEqual(w.menu.hidden, true);
  assert.strictEqual(w.attrs["aria-expanded"], "false");
  assert.deepStrictEqual(w.focused, []);
});

test("Escape closes an open choice and returns focus to the button; Escape does nothing when it is closed", () => {
  const w = world();
  w.listeners.document.keydown[0]({ key: "Escape" });
  assert.deepStrictEqual(w.focused, []);
  w.listeners.toggle.click();
  w.focused.length = 0;
  w.listeners.document.keydown[0]({ key: "Escape" });
  assert.strictEqual(w.menu.hidden, true);
  assert.deepStrictEqual(w.focused, ["export-menu-btn"]);
});

test("choosing a download closes the choice and returns focus to the button", () => {
  const w = world();
  w.listeners.toggle.click();
  w.focused.length = 0;
  w.listeners.menu.click({ target: w.first });
  assert.strictEqual(w.menu.hidden, true);
  assert.deepStrictEqual(w.focused, ["export-menu-btn"]);
});

test("a click on a hidden choice (the delete panel presses them) moves no focus and opens nothing", () => {
  const w = world();
  w.listeners.menu.click({ target: w.first });
  assert.strictEqual(w.menu.hidden, true);
  assert.deepStrictEqual(w.focused, []);
});

test("a click outside closes an open choice without moving focus, and a click inside the wrapper does not", () => {
  const w = world();
  w.listeners.toggle.click();
  w.focused.length = 0;
  w.listeners.document.click[0]({ target: w.inside });
  assert.strictEqual(w.menu.hidden, false);
  w.listeners.document.click[0]({ target: w.outside });
  assert.strictEqual(w.menu.hidden, true);
  assert.deepStrictEqual(w.focused, []);
});

test("the choice buttons line up (no inherited side margin) and every control is at least 44px tall", () => {
  const css = read("career", "dashboard-v8.css");
  assert.match(css, /\.export-menu \.btn-secondary \{ width: 100%; margin: 0; \}/);
  assert.match(css, /\.export-menu-wrap \.btn-secondary \{ min-height: 44px; \}/);
  assert.match(css, /\.export-menu\[hidden\] \{ display: none; \}/);
});

test("the two download choices highlight on hover and keyboard focus like the homepage cards, and the lift respects reduced motion", () => {
  const css = fs.readFileSync(path.join(__dirname, "..", "..", "..", "frontend", "career", "dashboard-v8.css"), "utf8");
  assert.match(css, /\.export-menu \.btn-secondary:hover, body\.chrome-v6\.dashboard-v4 \.export-menu \.btn-secondary:focus-visible \{ box-shadow: 0 10px 20px rgba\(0, 51, 149, 0\.18\)/);
  const motion = css.slice(css.indexOf("@media (prefers-reduced-motion: no-preference)", css.indexOf(".export-menu .btn-secondary:hover")));
  assert.match(motion.slice(0, 500), /translateY\(-2px\)/);
  assert.ok(!/\.export-menu[^{]*:hover[^{]*\{[^}]*translateY/.test(css.replace(/@media[\s\S]*?\n\}/g, "")), "the lift is only inside the reduced-motion guard");
  const js = fs.readFileSync(path.join(__dirname, "..", "..", "..", "frontend", "career", "js", "exportMenu.js"), "utf8");
  assert.ok(!/mouseenter|mouseover|:hover/.test(js), "the choice never opens on hover alone");
});
