// Career Profile is invite-only while it is in beta. This page never creates an account: submitting the form
// only explains that. (The real lock is in the sign-in service: self-registration is switched off for the
// user pool, so calling it directly does not work either. This page just says so kindly.)
const signupForm = document.getElementById("signup-form");
const signupError = document.getElementById("signup-error");

const INVITE_ONLY_MESSAGE = "Sorry, we can't create this account. Career Profile is currently in beta testing and is by invitation only.";

signupForm.addEventListener("submit", (e) => {
  e.preventDefault();
  signupError.textContent = "";
  const text = document.createElement("span");
  text.textContent = INVITE_ONLY_MESSAGE + " To ask for an invitation, ";
  const link = document.createElement("a");
  link.href = "mailto:yovanarathbone@creatingtomorrow.net?subject=" + encodeURIComponent("Career Profile beta invitation request");
  link.textContent = "email us";
  const rest = document.createTextNode(". If you were already invited, ");
  const login = document.createElement("a");
  login.href = "login.html";
  login.textContent = "log in here";
  signupError.append(text, link, rest, login, document.createTextNode("."));
  signupError.hidden = false;
});
