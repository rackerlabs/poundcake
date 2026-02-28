import { apiPost } from "./api-client.js";

export function buildNextUrl() {
  const path = window.location.pathname || "/";
  const search = window.location.search || "";
  return `${path}${search}`;
}

export function redirectToLogin(nextUrl = buildNextUrl()) {
  const target = new URL("/login", window.location.origin);
  if (nextUrl) {
    target.searchParams.set("next", nextUrl);
  }
  window.location.assign(target.toString());
}

export function getLoginNextTarget() {
  const params = new URLSearchParams(window.location.search);
  const raw = params.get("next");
  if (!raw) {
    return "/";
  }
  if (!raw.startsWith("/")) {
    return "/";
  }
  if (raw === "/login" || raw.startsWith("/login?")) {
    return "/";
  }
  return raw;
}

export async function checkSession() {
  const response = await fetch("/api/v1/settings", {
    method: "GET",
    credentials: "same-origin",
  });

  if (response.status === 401) {
    return { authenticated: false, settings: null };
  }

  // Some proxy/auth paths can redirect unauthenticated probes to /login.
  // Treat that as unauthenticated instead of failing JSON parsing.
  if (response.redirected && response.url.includes("/login")) {
    return { authenticated: false, settings: null };
  }

  if (!response.ok) {
    throw new Error(`Failed to check session (${response.status})`);
  }

  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) {
    return { authenticated: false, settings: null };
  }

  let settings;
  try {
    settings = await response.json();
  } catch {
    return { authenticated: false, settings: null };
  }
  return { authenticated: true, settings };
}

export async function login(username, password) {
  return apiPost("/api/v1/auth/login", { username, password }, { allow401: true });
}

export async function logout() {
  const response = await fetch("/api/v1/auth/logout", {
    method: "POST",
    credentials: "same-origin",
  });

  if (!response.ok && response.status !== 401) {
    throw new Error(`Logout failed (${response.status})`);
  }

  try {
    return await response.json();
  } catch {
    return null;
  }
}
