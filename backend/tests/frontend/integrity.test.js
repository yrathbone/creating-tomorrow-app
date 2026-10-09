// Outside scripts must be locked to a known fingerprint (risk-audit finding F-35): if the CDN or the package were ever
// tampered with, the browser would refuse to run it instead of running an attacker's code on the sign-in page.
// Run:  node --test backend/tests/frontend
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const FRONTEND = path.join(__dirname, "..", "..", "..", "frontend");
function htmlFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) return e.name === "fonts" || e.name === "img" ? [] : htmlFiles(full);
    return e.name.endsWith(".html") ? [full] : [];
  });
}

test("every script loaded from another website carries an integrity fingerprint and cross-origin mode", () => {
  let outside = 0;
  for (const file of htmlFiles(FRONTEND)) {
    const html = fs.readFileSync(file, "utf8");
    for (const tag of html.match(/<script\b[^>]*\bsrc="https?:\/\/[^"]+"[^>]*>/g) || []) {
      outside += 1;
      assert.match(tag, /\bintegrity="sha(256|384|512)-[A-Za-z0-9+/]+=*"/, `${path.relative(FRONTEND, file)}: ${tag}`);
      assert.match(tag, /\bcrossorigin="anonymous"/, `${path.relative(FRONTEND, file)}: ${tag}`);
    }
  }
  assert.ok(outside >= 1, "the sign-in page still loads the Cognito library");
});

test("the sign-in page pins the exact library version with a sha384 fingerprint", () => {
  const html = fs.readFileSync(path.join(FRONTEND, "career", "login.html"), "utf8");
  assert.match(html, /<script src="https:\/\/cdn\.jsdelivr\.net\/npm\/amazon-cognito-identity-js@6\.3\.20\/dist\/amazon-cognito-identity\.min\.js" integrity="sha384-SVW\/JUAWuaFjpcvT65qqpCfy5aD\/6\+mTPt046MJYXaNbaI70H1WE4fvhVc0iKOvi" crossorigin="anonymous"><\/script>/);
});

test("the sign-up page no longer loads the sign-in library it never uses", () => {
  const html = fs.readFileSync(path.join(FRONTEND, "career", "register.html"), "utf8");
  assert.ok(!html.includes("amazon-cognito-identity"), "no library");
  assert.ok(!html.includes("jsdelivr"), "no outside script host");
  const js = fs.readFileSync(path.join(FRONTEND, "career", "register.js"), "utf8");
  assert.ok(!js.includes("AmazonCognito"), "register.js does not use it");
});
