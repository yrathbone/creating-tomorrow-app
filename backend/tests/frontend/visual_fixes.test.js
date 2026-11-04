// Visual audit fixes for the public pages (VA-1 to VA-5, VA-7 to VA-9): readable sizes, spacing, contrast and tap targets.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
const css = fs.readFileSync(path.join(FRONTEND, "chrome-v6.css"), "utf8");
const block = css.slice(css.indexOf("public pages: readable sizes"));

const rule = (selector) => {
  const start = block.indexOf(selector);
  assert.ok(start >= 0, `missing rule: ${selector}`);
  return block.slice(start, block.indexOf("}", start) + 1);
};
const rem = (text) => parseFloat(text.match(/font-size:\s*([\d.]+)rem/)[1]);

function luminance(hex) {
  const v = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
  return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
}
const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + 0.05) / (Math.min(luminance(a), luminance(b)) + 0.05);

test("VA-1: homepage small print is at least 14px (13px for the quiet lines), nothing under 12px", () => {
  assert.strictEqual(rem(rule("body.chrome-v6:not(.dashboard-v4).home-v7 .h7-text, body.chrome-v6:not(.dashboard-v4).home-v7 .h7-link")), 0.875);
  assert.strictEqual(rem(rule("body.chrome-v6:not(.dashboard-v4).home-v7 .h7-free, body.chrome-v6:not(.dashboard-v4).home-v7 .h7-trust")), 0.8125);
  assert.strictEqual(rem(rule("body.chrome-v6:not(.dashboard-v4).home-v7 .h7-statement p")), 0.875);
  for (const m of block.matchAll(/font-size:\s*([\d.]+)rem/g)) assert.ok(parseFloat(m[1]) * 16 >= 12, `font under 12px: ${m[0]}`);
});

test("VA-2: card title, description and link have a clear gap on the homepage and the Learn and Tools pages", () => {
  assert.match(rule("body.chrome-v6:not(.dashboard-v4).home-v7 .h7-title"), /margin-bottom: 0\.5rem/);
  assert.match(rule("body.chrome-v6:not(.dashboard-v4).home-v7 .h7-guide .h7-text"), /margin-bottom: 0\.75rem/);
  assert.match(rule("body.chrome-v6:not(.dashboard-v4).pages-v4 .hv-guide b"), /margin-bottom: 0\.5rem/);
  assert.match(rule("body.chrome-v6:not(.dashboard-v4).pages-v4 span.hv-vdesc"), /margin-bottom: 0\.75rem/);
});

test("VA-4 and VA-5: gold and grey text pass 4.5:1 on white", () => {
  const gold = rule("body.chrome-v6:not(.dashboard-v4) .ats-gold");
  const goldColor = gold.match(/color: (#[0-9a-f]{6});/i)[1];
  assert.ok(contrast(goldColor, "#ffffff") >= 4.5);
  assert.match(gold, /text-decoration-color: #ffb000/); // the gold stays as the underline
  const unclear = rule("body.chrome-v6:not(.dashboard-v4) .ats-compare-unclear .ats-compare-label");
  assert.ok(contrast(unclear.match(/color: (#[0-9a-f]{6});/i)[1], "#ffffff") >= 4.5);
  assert.ok(rem(unclear) * 16 >= 12);
});

test("VA-7 and VA-8: header and article links are at least 44px tall", () => {
  for (const sel of [
    "body.chrome-v6:not(.dashboard-v4) .nav-logo",
    "body.chrome-v6:not(.dashboard-v4) .nav-links a",
    "body.chrome-v6:not(.dashboard-v4) .ats-back-link",
    "body.chrome-v6:not(.dashboard-v4) .ats-next-link",
  ]) assert.match(rule(sel), /min-height: 44px/, sel);
});

test("VA-9: the phone field matches the other fields and the City and State row has room below it", () => {
  const styleCss = fs.readFileSync(path.join(FRONTEND, "style.css"), "utf8");
  assert.match(styleCss, /\.field input\[type="email"\],\s*\.field input\[type="tel"\],\s*\.field input\[type="password"\]/); // the phone field is styled like the others
  assert.match(rule('body.chrome-v6:not(.dashboard-v4) .field input[type="text"], body.chrome-v6:not(.dashboard-v4) .field input[type="email"]'), /min-height: 44px/);
  assert.match(rule("body.chrome-v6:not(.dashboard-v4) .field-row {"), /margin-bottom: 1\.25rem/);
});

test("the fixes keep the dashboard, the palette and the footer logo out of scope", () => {
  assert.ok(!/dashboard-v4\)[^{]*\.nav-logo[^{]*\{[^}]*#/.test(block));
  assert.ok(!/e5a100/i.test(block), "the amber footer logo (VA-6) is not changed here");
  assert.ok(!/font-family/.test(block), "no font change");
});
