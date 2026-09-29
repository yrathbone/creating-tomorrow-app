const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const loginBtn = document.getElementById("login-btn");

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.hidden = true;
  const email = document.getElementById("login-email").value.trim();
  const password = document.getElementById("login-password").value;

  loginBtn.disabled = true;
  try {
    const { accessToken } = await signIn(email, password);

    const res = await fetch("/api/career/me", {
      headers: { Authorization: "Bearer " + accessToken },
    });
    const body = await res.json();

    document.getElementById("step-login").hidden = true;
    document.getElementById("step-loggedin").hidden = false;
    document.getElementById("me-result").textContent = JSON.stringify(body, null, 2);
  } catch (err) {
    loginError.textContent = (err && err.message) || "Login failed.";
    loginError.hidden = false;
  } finally {
    loginBtn.disabled = false;
  }
});
