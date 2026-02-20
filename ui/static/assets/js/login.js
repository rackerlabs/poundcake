import { checkSession, getLoginNextTarget, login } from "./lib/auth.js";

function showError(message) {
  const box = document.getElementById("login-error");
  box.textContent = message;
  box.classList.add("is-open");
}

function clearError() {
  document.getElementById("login-error").classList.remove("is-open");
}

async function handleSubmit(event) {
  event.preventDefault();
  clearError();

  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  const button = document.getElementById("login-submit");

  if (!username || !password) {
    showError("Username and password are required.");
    return;
  }

  button.disabled = true;
  button.textContent = "Signing in...";

  try {
    await login(username, password);
    window.location.assign(getLoginNextTarget());
  } catch (error) {
    showError(error.message || "Invalid credentials");
    button.disabled = false;
    button.textContent = "Login";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  checkSession()
    .then((session) => {
      if (session.authenticated) {
        window.location.assign(getLoginNextTarget());
        return;
      }
      document.getElementById("login-form")?.addEventListener("submit", handleSubmit);
    })
    .catch(() => {
      document.getElementById("login-form")?.addEventListener("submit", handleSubmit);
    });
});
