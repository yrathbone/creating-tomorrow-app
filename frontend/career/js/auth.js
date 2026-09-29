/*
Cognito sign-up/sign-in calls (amazon-cognito-identity-js, loaded via CDN
script tag in login.html/register.html - no build step, per Decision 3).
Promise-wrapped versions of the SDK's callback-based API.

Access tokens are never persisted (no localStorage/sessionStorage) - the
locked design's own stated tradeoff (docs/CAREER_PROFILE_ARCHITECTURE_
AUDIT.md Deliverable C): a hard refresh means signing in again. This is
the Cognito ACCESS token (not the ID token) - it's what authorizes calls
to the backend (Decision 12); the ID token is unused here.
*/
const COGNITO_USER_POOL_ID = "us-east-2_uLhNvjpep";
const COGNITO_APP_CLIENT_ID = "5rfhr0o7799aa41a5odrt9i9hd";

const userPool = new AmazonCognitoIdentity.CognitoUserPool({
  UserPoolId: COGNITO_USER_POOL_ID,
  ClientId: COGNITO_APP_CLIENT_ID,
});

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
  const cognitoUser = new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool });
  return new Promise((resolve, reject) => {
    cognitoUser.confirmRegistration(code, true, (err, result) => {
      if (err) return reject(err);
      resolve(result);
    });
  });
}

function resendConfirmationCode(email) {
  const cognitoUser = new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool });
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
  const cognitoUser = new AmazonCognitoIdentity.CognitoUser({ Username: email, Pool: userPool });

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
