/*
Cognito sign-up/sign-in calls (amazon-cognito-identity-js, loaded via CDN
script tag in login.html/register.html - no build step, per Decision 3).
Promise-wrapped versions of the SDK's callback-based API.

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
const COGNITO_USER_POOL_ID = "us-east-2_uLhNvjpep";
const COGNITO_APP_CLIENT_ID = "5rfhr0o7799aa41a5odrt9i9hd";

// Every key the SDK writes for this app client starts with this prefix.
const COGNITO_KEY_PREFIX = "CognitoIdentityServiceProvider." + COGNITO_APP_CLIENT_ID + ".";

// Earlier versions let the SDK use its default (localStorage). Remove only this
// app client's leftover keys there; nothing else in localStorage is touched and
// the old tokens are not migrated (people simply sign in again).
function removeLegacyLocalStorageSession() {
  try {
    const stale = [];
    for (let i = 0; i < window.localStorage.length; i++) {
      const key = window.localStorage.key(i);
      if (key && key.indexOf(COGNITO_KEY_PREFIX) === 0) stale.push(key);
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

removeLegacyLocalStorageSession();
const cognitoSessionStorage = pickSessionStorage();

const userPool = new AmazonCognitoIdentity.CognitoUserPool({
  UserPoolId: COGNITO_USER_POOL_ID,
  ClientId: COGNITO_APP_CLIENT_ID,
  Storage: cognitoSessionStorage,
});

// A CognitoUser only uses the pool's storage if it is told to: without the Storage
// option it falls back to the SDK default (localStorage). Every user object we
// create goes through here so tokens are only ever cached in session storage.
function newCognitoUser(email) {
  return new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool, Storage: cognitoSessionStorage });
}

// Local indicator only: are there SDK keys in this tab? It says nothing about
// whether the session is still valid - getValidSession() and the backend decide that.
function hasStoredSessionKeys() {
  return !!cognitoSessionStorage.getItem(COGNITO_KEY_PREFIX + "LastAuthUser");
}

// Remove every SDK key for this app client from this tab's storage (the current
// user's, any other user's leftovers, device keys). Other keys are left alone.
function clearCognitoSessionKeys() {
  const mine = [];
  for (let i = 0; i < cognitoSessionStorage.length; i++) {
    const key = cognitoSessionStorage.key(i);
    if (key && key.indexOf(COGNITO_KEY_PREFIX) === 0) mine.push(key);
  }
  mine.forEach((key) => cognitoSessionStorage.removeItem(key));
}

// Restores the saved session through the SDK. Resolves with a valid
// CognitoUserSession (the SDK refreshes expired tokens with the refresh token);
// rejects when there is no session or it can no longer be refreshed.
let sessionInFlight = null;
function getValidSession() {
  if (sessionInFlight) return sessionInFlight;
  sessionInFlight = new Promise((resolve, reject) => {
    const cognitoUser = userPool.getCurrentUser();
    if (!cognitoUser) return reject(new Error("No saved session."));
    cognitoUser.getSession((err, session) => {
      if (err || !session || !session.isValid()) return reject(err || new Error("Session is not valid."));
      resolve(session);
    });
  });
  const clear = () => { sessionInFlight = null; };
  sessionInFlight.then(clear, clear);
  return sessionInFlight;
}

// Asks the SDK for a brand-new access token with the stored refresh token. Used
// once when the backend rejects a token the browser still believed was valid.
function forceRefreshSession() {
  return new Promise((resolve, reject) => {
    const cognitoUser = userPool.getCurrentUser();
    if (!cognitoUser) return reject(new Error("No saved session."));
    cognitoUser.getSession((err, session) => {
      if (err || !session) return reject(err || new Error("No saved session."));
      cognitoUser.refreshSession(session.getRefreshToken(), (refreshErr, fresh) => {
        if (refreshErr || !fresh) return reject(refreshErr || new Error("Refresh failed."));
        resolve(fresh);
      });
    });
  });
}

// Sign Out: the SDK's signOut(callback) clears this user's keys and asks Cognito to
// revoke this device's refresh token (if that fails, e.g. offline, we carry on);
// then every remaining SDK key for this app client is removed too.
function signOutCurrentUser() {
  const cognitoUser = userPool.getCurrentUser();
  const revoked = new Promise((resolve) => {
    if (!cognitoUser) return resolve();
    const giveUp = setTimeout(resolve, 4000);
    cognitoUser.signOut(() => { clearTimeout(giveUp); resolve(); });
  });
  return revoked.then(clearCognitoSessionKeys, clearCognitoSessionKeys);
}

function signUp(email, password) {
  const attributeList = [
    new AmazonCognitoIdentity.CognitoUserAttribute({ Name: "email", Value: email }),
  ];
  return new Promise((resolve, reject) => {
    userPool.signUp(email, password, attributeList, null, (err, result) => {
      if (err) return reject(err);
      resolve(result);
    });
  });
}

function confirmRegistration(email, code) {
  const cognitoUser = newCognitoUser(email);
  return new Promise((resolve, reject) => {
    cognitoUser.confirmRegistration(code, true, (err, result) => {
      if (err) return reject(err);
      resolve(result);
    });
  });
}

function resendConfirmationCode(email) {
  const cognitoUser = newCognitoUser(email);
  return new Promise((resolve, reject) => {
    cognitoUser.resendConfirmationCode((err, result) => {
      if (err) return reject(err);
      resolve(result);
    });
  });
}

function signIn(email, password) {
  const authDetails = new AmazonCognitoIdentity.AuthenticationDetails({
    Username: email,
    Password: password,
  });
  const cognitoUser = newCognitoUser(email);

  return new Promise((resolve, reject) => {
    cognitoUser.authenticateUser(authDetails, {
      onSuccess: (session) => {
        resolve({
          accessToken: session.getAccessToken().getJwtToken(),
          idToken: session.getIdToken().getJwtToken(),
        });
      },
      onFailure: (err) => reject(err),
    });
  });
}
