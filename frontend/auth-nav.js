/*
Public-page header state (Phase 1B). Tiny, no Cognito library, no network.

1. Removes this app client's leftover Cognito keys from localStorage (older versions
   of the site stored sign-in tokens there). Only keys with the app client's prefix
   are removed; nothing else in localStorage is touched and nothing is migrated.
2. Looks for the Cognito session keys in this tab's sessionStorage and, if present,
   changes the header's "Sign In" link to "My Career" (same /career/login.html page)
   and hides the homepage's "Already have an account? Sign in" prompt.

The stored keys are ONLY a local hint for choosing a label. They are not
authentication, authorization, or permission to see anything: the Cognito library
(on /career/login.html) and the backend decide whether a session is valid. If the
hint is stale, the link simply lands on the normal login form.
*/
(function () {
  // The Cognito SDK namespace. The app client id is read from the stored key names at run time, never written here (F9).
  var namespace = "CognitoIdentityServiceProvider.";
  var lastUser = /^CognitoIdentityServiceProvider\.([^.]+)\.LastAuthUser$/;

  try {
    var stale = [];
    for (var i = 0; i < window.localStorage.length; i++) {
      var key = window.localStorage.key(i);
      if (key && key.indexOf(namespace) === 0) stale.push(key);
    }
    stale.forEach(function (k) { window.localStorage.removeItem(k); });
  } catch (e) { /* localStorage unavailable */ }

  try {
    var signedIn = false;
    for (var s = 0; s < window.sessionStorage.length && !signedIn; s++) {
      var match = lastUser.exec(window.sessionStorage.key(s) || "");
      if (!match) continue;
      var clientPrefix = namespace + match[1] + ".";
      var user = window.sessionStorage.getItem(clientPrefix + "LastAuthUser");
      if (user && window.sessionStorage.getItem(clientPrefix + user + ".refreshToken")) signedIn = true;
    }
    if (signedIn) {
      var links = document.querySelectorAll("a.nav-account");
      for (var j = 0; j < links.length; j++) links[j].textContent = "My Career";
      // The homepage's secondary "Already have an account? Sign in" prompt is redundant
      // now. It sits further down the page than this script, so hide it with a rule
      // instead of looking it up (no flash, no waiting for the page to finish loading).
      var hide = document.createElement("style");
      hide.textContent = ".hero-signin { display: none; }";
      document.head.appendChild(hide);
    }
  } catch (e) { /* sessionStorage unavailable: keep "Sign In" */ }
})();
