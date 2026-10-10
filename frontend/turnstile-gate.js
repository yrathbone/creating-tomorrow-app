/* The invisible bot check (Cloudflare Turnstile) for the public AI tools.
   One small shared script, loaded by the five tool pages before their own script. It does nothing unless the server says the check
   is on (GET /api/turnstile-config), so the pages work exactly as before until the keys exist.

   When it is on: it loads Cloudflare's script, gets a short-lived single-use pass, and adds it to every POST to one of the nine
   AI endpoints as the X-Turnstile-Token header. A new pass is fetched after each use. Nothing here is a secret: the site key is
   public by design. If the pass cannot be had in time the request is sent without one and the server answers with a friendly
   message (the tools already show the server's message). */
(function () {
  "use strict";

  // Keep this list identical to PUBLIC_AI_PATHS in backend/abuse_guard.py (a test compares the two).
  var AI_PATHS = [
    "/api/analyze", "/api/refine", "/api/elevate-start", "/api/elevate-discover", "/api/elevate-finalize",
    "/api/profile-review", "/api/prepare", "/api/scratch-entry", "/api/scratch-finalize"
  ];
  var CONFIG_URL = "/api/turnstile-config";
  var CLOUDFLARE_SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
  var TOKEN_WAIT_MS = 25000;   // how long a click waits for the pass before going without one
  var CONFIG_WAIT_MS = 3000;   // how long a click waits for the page to learn whether the check is on

  var realFetch = window.fetch ? window.fetch.bind(window) : null;
  if (!realFetch) return;

  var state = { enabled: false, siteKey: null, widgetId: null, token: null, waiters: [] };

  function pathOf(input) {
    try {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      return new URL(url, window.location.href).pathname;
    } catch (e) {
      return "";
    }
  }

  function isGated(input, init) {
    var method = ((init && init.method) || (input && input.method) || "GET").toUpperCase();
    return method === "POST" && AI_PATHS.indexOf(pathOf(input)) !== -1;
  }

  function deliver(token) {
    state.token = token;
    var waiting = state.waiters.splice(0);
    waiting.forEach(function (resolve) { resolve(token); });
  }

  function getToken() {
    if (state.token) return Promise.resolve(state.token);
    return new Promise(function (resolve) {
      var timer = setTimeout(function () {
        var i = state.waiters.indexOf(done);
        if (i !== -1) state.waiters.splice(i, 1);
        resolve(null);
      }, TOKEN_WAIT_MS);
      function done(token) { clearTimeout(timer); resolve(token); }
      state.waiters.push(done);
    });
  }

  function refresh() {
    state.token = null;
    try {
      if (window.turnstile && state.widgetId !== null) window.turnstile.reset(state.widgetId);
    } catch (e) { /* the next request simply goes without a pass and gets the friendly message */ }
  }

  function render() {
    var box = document.createElement("div");
    box.id = "ct-turnstile";
    // "interaction-only": invisible unless Cloudflare needs the visitor to do something, in which case it shows here.
    box.style.cssText = "position:fixed;right:1rem;bottom:1rem;z-index:60;";
    document.body.appendChild(box);
    state.widgetId = window.turnstile.render(box, {
      sitekey: state.siteKey,
      appearance: "interaction-only",
      callback: deliver,
      "expired-callback": function () { state.token = null; },
      "error-callback": function () { state.token = null; },
      retry: "auto"
    });
  }

  function start() {
    var script = document.createElement("script");
    script.src = CLOUDFLARE_SCRIPT;
    script.async = true;
    script.defer = true;
    script.onload = function () {
      if (window.turnstile) render();
    };
    document.head.appendChild(script);
  }

  var configReady = realFetch(CONFIG_URL, { cache: "no-store" })
    .then(function (res) { return res.ok ? res.json() : { enabled: false }; })
    .then(function (cfg) {
      if (cfg && cfg.enabled && cfg.site_key) {
        state.enabled = true;
        state.siteKey = cfg.site_key;
        var begin = function () { start(); };
        if (document.body) begin();
        else document.addEventListener("DOMContentLoaded", begin);
      }
    })
    .catch(function () { /* check stays off in this browser; the server decides what to do */ });

  window.fetch = function (input, init) {
    if (!isGated(input, init)) return realFetch(input, init);
    var wait = new Promise(function (resolve) { setTimeout(resolve, CONFIG_WAIT_MS); });
    return Promise.race([configReady, wait]).then(function () {
      if (!state.enabled) return realFetch(input, init);
      return getToken().then(function (token) {
        var options = Object.assign({}, init || {});
        var headers = new Headers(options.headers || {});
        if (token) headers.set("X-Turnstile-Token", token);
        options.headers = headers;
        var sent = realFetch(input, options);
        sent.then(refresh, refresh);   // a pass is single-use: ask for the next one now
        return sent;
      });
    });
  };
})();
