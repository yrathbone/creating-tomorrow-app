/*
Cognito sign-up/sign-in calls (amazon-cognito-identity-js, loaded via CDN
script tag in login.html - no build step, per Decision 3).
Promise-wrapped versions of the SDK's callback-based API.

Configuration (no fallback): the user pool id and app client id are NOT written
in this file. They come from the server (GET /api/career/auth-config, read-only,
values from the server's environment). Every action that needs them waits for
that configuration first. If it cannot be loaded, the action fails with an error
whose code is "AuthUnavailable" and a message the page can show; a later attempt
asks the server again, so the page can recover without a reload.

Session storage (Phase 1B): the SDK caches its tokens (access, ID, refresh)
in whatever Storage the pool is given. We hand it sessionStorage, so a sign-in
lasts for this browser tab only: reloads and page-to-page navigation in the
same tab keep it, closing the tab ends it, and nothing is written to
localStorage. (sessionStorage is per tab - a new tab starts signed out.)
getCurrentUser()+getSession() restore it and refresh expired tokens through
the SDK; there is no custom token logic here. The ACCESS token authorizes calls
to the backend (Decision 12); the ID token is unused.
Sign Out clears the SDK's keys; an access token already issued can still be
accepted by the backend until it expires (the backend does not check revocation).
*/
const AUTH_CONFIG_URL = "/api/career/auth-config";
const AUTH_UNAVAILABLE_MESSAGE = "Sign-in is unavailable right now. Check your connection and try again.";
// Every key the Cognito SDK writes, for any app client. Used only to clear them; never to decide anything else.
const COGNITO_SDK_KEY_PREFIX = "CognitoIdentityServiceProvider.";

// Set once the configuration has loaded and passed the checks below. Nothing here is a default.
let cognitoConfig = null;
let cognitoKeyPrefix = null;      // every SDK key for this app client starts with this
let cognitoSessionStorage = null;
let userPool = null;
let authReadyPromise = null;      // the one in-flight or finished attempt; cleared on failure so the next call retries

// An error the page can recognise. Its message is safe to show as it is.
function authUnavailableError() {
  const err = new Error(AUTH_UNAVAILABLE_MESSAGE);
  err.code = "AuthUnavailable";
  return err;
}

function isAuthUnavailable(err) {
  return !!err && err.code === "AuthUnavailable";
}

// The configuration must have the three values in the expected shape, and the pool's region must match the region.
function validCognitoConfig(c) {
  if (!c || typeof c !== "object") return false;
  if (typeof c.region !== "string" || typeof c.user_pool_id !== "string" || typeof c.app_client_id !== "string") return false;
  const pool = /^([a-z]{2}(?:-[a-z]+)+-\d)_[A-Za-z0-9]{1,40}$/.exec(c.user_pool_id);
  return /^[a-z]{2}(?:-[a-z]+)+-\d$/.test(c.region)
    && !!pool && pool[1] === c.region
    && /^[A-Za-z0-9]{10,64}$/.test(c.app_client_id);
}

// Earlier versions let the SDK use its default (localStorage). Remove only this
// app client's leftover keys there; nothing else in localStorage is touched and
// the old tokens are not migrated (people simply sign in again).
function removeLegacyLocalStorageSession(prefix) {
  try {
    const stale = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key && key.indexOf(prefix) === 0) stale.push(key);
    }
    stale.forEach((key) => window.localStorage.removeItem(key));
  } catch (e) {
    // localStorage unavailable: nothing to clean.
  }
}

// Same interface as Storage. Used only if sessionStorage is blocked, so the SDK
// can never fall back to its own default of localStorage.
function createMemoryStorage() {
  const data = {};
  return {
    get length() { return Object.keys(data).length; },
    key(i) { return Object.keys(data)[i] || null; },
    getItem(k) { return Object.prototype.hasOwnProperty.call(data, k) ? data[k] : null; },
    setItem(k, v) { data[k] = String(v); },
    removeItem(k) { delete data[k]; },
    clear() { Object.keys(data).forEach((k) => delete data[k]); },
  };
}

function pickSessionStorage() {
  try {
    const probe = "ct.storage-probe";
    window.sessionStorage.setItem(probe, "1");
    window.sessionStorage.removeItem(probe);
    return window.sessionStorage;
  } catch (e) {
    return createMemoryStorage();
  }
}

// Builds the pool from a configuration that has already passed validCognitoConfig.
function initCognito(config) {
  cognitoConfig = config;
  cognitoKeyPrefix = "CognitoIdentityServiceProvider." + config.app_client_id + ".";
  removeLegacyLocalStorageSession(cognitoKeyPrefix);
  cognitoSessionStorage = pickSessionStorage();
  userPool = new AmazonCognitoIdentity.CognitoUserPool({
    UserPoolId: config.user_pool_id,
    ClientId: config.app_client_id,
    Storage: cognitoSessionStorage,
  });
}

// Resolves true once the configuration is loaded and the pool is ready. Rejects with an AuthUnavailable error otherwise.
// Only one request is in flight at a time, and a success is kept for the rest of the page's life.
function ensureAuthReady() {
  if (authReadyPromise) return authReadyPromise;
  authReadyPromise = fetch(AUTH_CONFIG_URL, { cache: "no-store", credentials: "same-origin" })
    .then((res) => {
      if (!res.ok) throw new Error("Sign-in configuration answered " + res.status);
      return res.json();
    })
    .then((config) => {
      if (!validCognitoConfig(config)) throw new Error("Sign-in configuration is malformed.");
      initCognito(config);
      return true;
    })
    .catch(() => {
      authReadyPromise = null;   // a later call asks the server again
      throw authUnavailableError();
    });
  return authReadyPromise;
}

// The page's "Try again" button calls this.
function retryAuthConfig() {
  authReadyPromise = null;
  return ensureAuthReady();
}

// A CognitoUser only uses the pool's storage if it is told to: without the Storage
// option it falls back to the SDK default (localStorage). Every user object we
// create goes through here so tokens are only ever cached in session storage.
function newCognitoUser(email) {
  return new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool, Storage: cognitoSessionStorage });
}

// Local indicator only: are there SDK keys in this tab? It says nothing about
// whether the session is still valid - getValidSession() and the backend decide that.
// Before the configuration has loaded it answers false (the caller waits with ensureAuthReady first).
function hasStoredSessionKeys() {
  if (!cognitoSessionStorage) return false;
  return !!cognitoSessionStorage.getItem(cognitoKeyPrefix + "LastAuthUser");
}

// Page-start hint only (no configuration needed): does this tab hold any SDK sign-in marker? Used to avoid
// flashing the login form. It never decides anything about access.
function looksLikeStoredSession() {
  try {
    for (let i = 0; i < window.sessionStorage.length; i++) {
      const key = window.sessionStorage.key(i);
      if (key && key.indexOf("CognitoIdentityServiceProvider.") === 0 && key.slice(-".LastAuthUser".length) === ".LastAuthUser") return true;
    }
  } catch (e) {
    // sessionStorage unavailable: no hint.
  }
  return false;
}

// Remove every SDK key for this app client from this tab's storage (the current
// user's, any other user's leftovers, device keys). Other keys are left alone.
// Does nothing before the configuration has loaded: the prefix is not known yet.
function clearCognitoSessionKeys() {
  if (!cognitoSessionStorage) return;
  const mine = [];
  for (let i = 0; i < cognitoSessionStorage.length; i++) {
    const key = cognitoSessionStorage.key(i);
    if (key && key.indexOf(cognitoKeyPrefix) === 0) mine.push(key);
  }
  mine.forEach((key) => cognitoSessionStorage.removeItem(key));
}

// Restores the saved session through the SDK. Resolves with a valid
// CognitoUserSession (the SDK refreshes expired tokens with the refresh token);
// rejects when there is no session or it can no longer be refreshed. Waits for the configuration first.
let sessionInFlight = null;
function getValidSession() {
  if (sessionInFlight) return sessionInFlight;
  sessionInFlight = ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const cognitoUser = userPool.getCurrentUser();
    if (!cognitoUser) return reject(new Error("No saved session."));
    cognitoUser.getSession((err, session) => {
      if (err || !session || !session.isValid()) return reject(err || new Error("Session is not valid."));
      resolve(session);
    });
  }));
  const clear = () => { sessionInFlight = null; };
  sessionInFlight.then(clear, clear);
  return sessionInFlight;
}

// Asks the SDK for a brand-new access token with the stored refresh token. Used
// once when the backend rejects a token the browser still believed was valid.
function forceRefreshSession() {
  return ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const cognitoUser = userPool.getCurrentUser();
    if (!cognitoUser) return reject(new Error("No saved session."));
    cognitoUser.getSession((err, session) => {
      if (err || !session) return reject(err || new Error("No saved session."));
      cognitoUser.refreshSession(session.getRefreshToken(), (refreshErr, fresh) => {
        if (refreshErr || !fresh) return reject(refreshErr || new Error("Refresh failed."));
        resolve(fresh);
      });
    });
  }));
}

// Removes every Cognito SDK key from this tab (session storage, and any leftover in local storage), for any app client.
// Needs no configuration and no network. Keys that are not the SDK's are never touched: the notice, the Career
// Profile draft and every other key stay as they are.
function clearAllCognitoKeysInTab() {
  const stores = [];
  try { stores.push(window.sessionStorage); } catch (e) { /* unavailable: nothing to clear there */ }
  if (cognitoSessionStorage && stores.indexOf(cognitoSessionStorage) < 0) stores.push(cognitoSessionStorage);
  try { stores.push(window.localStorage); } catch (e) { /* unavailable: nothing to clear there */ }
  stores.forEach((store) => {
    try {
      const mine = [];
      for (let i = 0; i < store.length; i++) {
        const key = store.key(i);
        if (key && key.indexOf(COGNITO_SDK_KEY_PREFIX) === 0) mine.push(key);
      }
      mine.forEach((key) => store.removeItem(key));
    } catch (e) {
      // This store cannot be read: there is nothing this code can clear in it.
    }
  });
}

// Sign Out. Two cases:
// - The configuration is loaded: the SDK's signOut asks Cognito to revoke this device's refresh token (if that fails,
//   e.g. offline, we carry on); then the local keys are removed.
// - The configuration is NOT loaded (an outage, or not yet tried): there is no pool to ask, so the local keys are
//   removed at once, without waiting for the network. The device's refresh token is then not revoked at Cognito by this
//   action; it is no longer usable from this tab.
// Either way, nothing unrelated in storage is touched (the sign-in notice, for example, stays).
function signOutCurrentUser() {
  if (cognitoConfig) {
    const cognitoUser = userPool.getCurrentUser();
    const revoked = new Promise((resolve) => {
      if (!cognitoUser) return resolve();
      const giveUp = setTimeout(resolve, 4000);
      cognitoUser.signOut(() => { clearTimeout(giveUp); resolve(); });
    });
    return revoked.then(clearAllCognitoKeysInTab, clearAllCognitoKeysInTab);
  }
  clearAllCognitoKeysInTab();
  return Promise.resolve();
}

// Permanently removes the signed-in person's own sign-in account from Cognito (the SDK's deleteUser, which
// needs their valid session). Only called after their saved data has been erased on our side.
function deleteCurrentCognitoUser() {
  return ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const cognitoUser = userPool.getCurrentUser();
    if (!cognitoUser) return reject(new Error("No saved session."));
    cognitoUser.getSession((err, session) => {
      if (err || !session) return reject(err || new Error("No saved session."));
      cognitoUser.deleteUser((deleteErr) => (deleteErr ? reject(deleteErr) : resolve()));
    });
  }));
}

function signUp(email, password) {
  return ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const attributeList = [
      new AmazonCognitoIdentity.CognitoUserAttribute({ Name: "email", Value: email }),
    ];
    userPool.signUp(email, password, attributeList, null, (err, result) => {
      if (err) return reject(err);
      resolve(result);
    });
  }));
}

function confirmRegistration(email, code) {
  return ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const cognitoUser = newCognitoUser(email);
    cognitoUser.confirmRegistration(code, true, (err, result) => {
      if (err) return reject(err);
      resolve(result);
    });
  }));
}

function resendConfirmationCode(email) {
  return ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const cognitoUser = newCognitoUser(email);
    cognitoUser.resendConfirmationCode((err, result) => {
      if (err) return reject(err);
      resolve(result);
    });
  }));
}

function signIn(email, password) {
  return ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const authDetails = new AmazonCognitoIdentity.AuthenticationDetails({
      Username: email,
      Password: password,
    });
    const cognitoUser = newCognitoUser(email);

    cognitoUser.authenticateUser(authDetails, {
      onSuccess: (session) => {
        resolve({
          accessToken: session.getAccessToken().getJwtToken(),
          idToken: session.getIdToken().getJwtToken(),
        });
      },
      onFailure: (err) => reject(err),
      // An invited person's first sign-in uses the temporary password from their invitation email.
      // Cognito then requires them to choose their own: hand the page a function that finishes the sign-in.
      newPasswordRequired: () => {
        resolve({
          newPasswordRequired: true,
          completeNewPassword: (newPassword) => new Promise((done, fail) => {
            cognitoUser.completeNewPasswordChallenge(newPassword, {}, {
              onSuccess: (session) => done({
                accessToken: session.getAccessToken().getJwtToken(),
                idToken: session.getIdToken().getJwtToken(),
              }),
              onFailure: (err) => fail(err),
            });
          }),
        });
      },
    });
  }));
}

// "Forgot password": Cognito emails a code to the person's verified address (nothing is sent
// from our server). The page then sends the code back with the new password. The SDK reports
// "code sent" through inputVerificationCode and only calls onSuccess after the reset is done.
function requestPasswordReset(email) {
  return ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const cognitoUser = newCognitoUser(email);
    cognitoUser.forgotPassword({
      onSuccess: () => resolve(),
      onFailure: (err) => reject(err),
      inputVerificationCode: () => resolve(),
    });
  }));
}

function confirmPasswordReset(email, code, newPassword) {
  return ensureAuthReady().then(() => new Promise((resolve, reject) => {
    const cognitoUser = newCognitoUser(email);
    cognitoUser.confirmPassword(code, newPassword, {
      onSuccess: () => resolve(),
      onFailure: (err) => reject(err),
    });
  }));
}
