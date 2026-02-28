let unauthorizedHandler = null;

export class ApiError extends Error {
  constructor(message, status, payload = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

async function parseResponse(response) {
  if (response.status === 204) {
    return null;
  }

  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function request(method, path, options = {}) {
  const {
    body,
    headers = {},
    allow401 = false,
    raw = false,
    signal,
  } = options;

  const init = {
    method,
    headers: {
      ...headers,
    },
    credentials: "same-origin",
    signal,
  };

  if (body !== undefined) {
    if (!(body instanceof FormData) && !init.headers["Content-Type"]) {
      init.headers["Content-Type"] = "application/json";
    }
    init.body = body instanceof FormData ? body : JSON.stringify(body);
  }

  const response = await fetch(path, init);

  if (response.status === 401 && !allow401 && typeof unauthorizedHandler === "function") {
    unauthorizedHandler();
  }

  if (raw) {
    return response;
  }

  const payload = await parseResponse(response);
  if (!response.ok) {
    const message =
      typeof payload === "string"
        ? payload
        : payload?.detail || `${method} ${path} failed (${response.status})`;
    throw new ApiError(message, response.status, payload);
  }

  return payload;
}

export function apiGet(path, options) {
  return request("GET", path, options);
}

export function apiPost(path, body, options = {}) {
  return request("POST", path, { ...options, body });
}

export function apiPut(path, body, options = {}) {
  return request("PUT", path, { ...options, body });
}

export function apiPatch(path, body, options = {}) {
  return request("PATCH", path, { ...options, body });
}

export function apiDelete(path, options = {}) {
  return request("DELETE", path, options);
}
