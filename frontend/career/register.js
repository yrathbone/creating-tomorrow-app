const signupForm = document.getElementById("signup-form");
const signupError = document.getElementById("signup-error");
const signupBtn = document.getElementById("signup-btn");

const confirmForm = document.getElementById("confirm-form");
const confirmError = document.getElementById("confirm-error");
const confirmBtn = document.getElementById("confirm-btn");
const resendBtn = document.getElementById("resend-btn");
const resendMsg = document.getElementById("confirm-resend-msg");

let pendingEmail = "";

signupForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  signupError.hidden = true;
  const email = document.getElementById("signup-email").value.trim();
  const password = document.getElementById("signup-password").value;

  signupBtn.disabled = true;
  try {
    await signUp(email, password);
    pendingEmail = email;
    document.getElementById("confirm-email-display").textContent = email;
    document.getElementById("step-signup").hidden = true;
    document.getElementById("step-confirm").hidden = false;
  } catch (err) {
    signupError.textContent = (err && err.message) || "Something went wrong creating your account.";
    signupError.hidden = false;
  } finally {
    signupBtn.disabled = false;
  }
});

confirmForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  confirmError.hidden = true;
  const code = document.getElementById("confirm-code").value.trim();

  confirmBtn.disabled = true;
  try {
    await confirmRegistration(pendingEmail, code);
    document.getElementById("step-confirm").hidden = true;
    document.getElementById("step-done").hidden = false;
  } catch (err) {
    confirmError.textContent = (err && err.message) || "That code didn't work.";
    confirmError.hidden = false;
  } finally {
    confirmBtn.disabled = false;
  }
});

resendBtn.addEventListener("click", async () => {
  resendMsg.hidden = true;
  confirmError.hidden = true;
  try {
    await resendConfirmationCode(pendingEmail);
    resendMsg.textContent = "A new code has been sent.";
    resendMsg.hidden = false;
  } catch (err) {
    confirmError.textContent = (err && err.message) || "Couldn't resend the code.";
    confirmError.hidden = false;
  }
});
